import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { Camera, Clock, Radio, Trash2, Users, X } from 'lucide-react';
import {
  ApiError,
  createStationAlias,
  deleteStationAlias,
  listActivityLog,
  listStationAliases,
  listUsers,
  removeAvatar,
  updateAvatar,
  updateProfile,
  updateUserRole,
} from '../api/client';
import type { ActivityLogEntry, StationAlias, User, UserRole } from '../api/contracts';
import { LimitedRowsControls, ROW_PAGE_SIZE, useLimitedRows } from '../components/LimitedRows';

const ROLES: UserRole[] = ['owner', 'admin', 'member'];

function RoleBadge({ role }: { role: UserRole }) {
  return <span className={`status status-${role === 'owner' ? 'complete' : role === 'admin' ? 'review' : 'setup'}`}>{role}</span>;
}

const AVATAR_ALLOWED_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];
const AVATAR_MAX_UPLOAD_BYTES = 15 * 1024 * 1024;
// The crop step below always produces a square image well under this --
// this cap is just the raw file someone picks off disk, before cropping.
const AVATAR_CROP_FRAME_SIZE = 240;
const AVATAR_OUTPUT_SIZE = 480;
const AVATAR_MAX_ZOOM = 3;

function initialsFor(displayName: string, email: string): string {
  const source = displayName.trim() || email;
  const words = source.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

export function AvatarCircle({ user, size = 64 }: { user: User; size?: number }) {
  if (user.avatarUrl) {
    return (
      <img
        className="avatar-circle avatar-circle-photo"
        src={user.avatarUrl}
        alt=""
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <div className="avatar-circle avatar-circle-initials" style={{ width: size, height: size, fontSize: size * 0.36 }}>
      {initialsFor(user.displayName, user.email)}
    </div>
  );
}

type CropOffset = { offsetX: number; offsetY: number };

// A minimal, dependency-free crop step: drag to pan, a slider to zoom, both
// constrained so the crop frame is always fully covered by the image. Saving
// rasterizes exactly the visible square onto a fixed-size canvas -- the
// backend never sees the original, uncropped file.
function AvatarCropModal({
  file,
  onCancel,
  onSave,
}: {
  file: File;
  onCancel: () => void;
  onSave: (dataUrl: string) => Promise<void>;
}) {
  // A data: URI rather than a blob: URL from URL.createObjectURL -- the
  // latter needs an explicit revokeObjectURL on cleanup, and React 18
  // StrictMode's dev-only double-invocation of effects (mount, cleanup,
  // mount again) revokes it immediately after creating it, breaking the
  // image load with no such issue in the production build (caught by
  // testing against the dev server, where StrictMode is active). A data
  // URI has no such external resource or revoke step to get out of sync.
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const dragState = useRef<{ startX: number; startY: number; startOffsetX: number; startOffsetY: number } | null>(null);

  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [offset, setOffset] = useState<CropOffset>({ offsetX: 0, offsetY: 0 });
  const [zoom, setZoom] = useState(1);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const reader = new FileReader();
    reader.onload = () => setPreviewUrl(typeof reader.result === 'string' ? reader.result : null);
    reader.readAsDataURL(file);
  }, [file]);

  const baseScale = naturalSize ? AVATAR_CROP_FRAME_SIZE / Math.min(naturalSize.width, naturalSize.height) : 1;

  function clampOffset(candidate: CropOffset, atZoom: number): CropOffset {
    if (!naturalSize) return { offsetX: 0, offsetY: 0 };
    const displayScale = baseScale * atZoom;
    const minX = Math.min(0, AVATAR_CROP_FRAME_SIZE - naturalSize.width * displayScale);
    const minY = Math.min(0, AVATAR_CROP_FRAME_SIZE - naturalSize.height * displayScale);
    return {
      offsetX: Math.min(0, Math.max(minX, candidate.offsetX)),
      offsetY: Math.min(0, Math.max(minY, candidate.offsetY)),
    };
  }

  function handleImageLoad() {
    const img = imgRef.current;
    if (!img) return;
    const size = { width: img.naturalWidth, height: img.naturalHeight };
    setNaturalSize(size);
    const scale = AVATAR_CROP_FRAME_SIZE / Math.min(size.width, size.height);
    setOffset({
      offsetX: (AVATAR_CROP_FRAME_SIZE - size.width * scale) / 2,
      offsetY: (AVATAR_CROP_FRAME_SIZE - size.height * scale) / 2,
    });
    setZoom(1);
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (!naturalSize) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragState.current = { startX: event.clientX, startY: event.clientY, startOffsetX: offset.offsetX, startOffsetY: offset.offsetY };
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!dragState.current) return;
    const dx = event.clientX - dragState.current.startX;
    const dy = event.clientY - dragState.current.startY;
    setOffset(clampOffset({ offsetX: dragState.current.startOffsetX + dx, offsetY: dragState.current.startOffsetY + dy }, zoom));
  }

  function handlePointerUp() {
    dragState.current = null;
  }

  function handleZoomChange(nextZoom: number) {
    setZoom(nextZoom);
    setOffset((current) => clampOffset(current, nextZoom));
  }

  async function handleSave() {
    const img = imgRef.current;
    if (!naturalSize || !img) return;
    setError(null);
    setIsSaving(true);
    try {
      const displayScale = baseScale * zoom;
      const sourceScale = 1 / displayScale;
      const sourceSize = AVATAR_CROP_FRAME_SIZE * sourceScale;

      const canvas = document.createElement('canvas');
      canvas.width = AVATAR_OUTPUT_SIZE;
      canvas.height = AVATAR_OUTPUT_SIZE;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Could not prepare the image.');
      ctx.drawImage(
        img,
        -offset.offsetX * sourceScale,
        -offset.offsetY * sourceScale,
        sourceSize,
        sourceSize,
        0,
        0,
        AVATAR_OUTPUT_SIZE,
        AVATAR_OUTPUT_SIZE,
      );
      await onSave(canvas.toDataURL('image/jpeg', 0.9));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save this photo.');
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="Crop your photo">
      <div className="modal-card avatar-crop-card">
        <div className="modal-header">
          <h2>Crop your photo</h2>
          <button type="button" className="icon-button" onClick={onCancel} aria-label="Close">
            <X size={18} aria-hidden />
          </button>
        </div>
        <div
          className="avatar-crop-frame"
          style={{ width: AVATAR_CROP_FRAME_SIZE, height: AVATAR_CROP_FRAME_SIZE }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          {previewUrl && (
            <img
              ref={imgRef}
              src={previewUrl}
              onLoad={handleImageLoad}
              alt=""
              draggable={false}
              style={
                naturalSize
                  ? {
                      width: naturalSize.width * baseScale * zoom,
                      height: naturalSize.height * baseScale * zoom,
                      transform: `translate(${offset.offsetX}px, ${offset.offsetY}px)`,
                    }
                  : undefined
              }
            />
          )}
        </div>
        <label className="avatar-crop-zoom">
          Zoom
          <input
            type="range"
            min={1}
            max={AVATAR_MAX_ZOOM}
            step={0.01}
            value={zoom}
            disabled={!naturalSize}
            onChange={(event) => handleZoomChange(Number(event.target.value))}
          />
        </label>
        {error && <p className="inline-error">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onCancel} disabled={isSaving}>
            Cancel
          </button>
          <button type="button" className="primary-button" onClick={() => void handleSave()} disabled={isSaving || !naturalSize}>
            {isSaving ? 'Saving…' : 'Save photo'}
          </button>
        </div>
      </div>
    </div>
  );
}

function ProfilePhotoPanel({ currentUser, onUserUpdated }: { currentUser: User; onUserUpdated: (user: User) => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ''; // lets picking the exact same file again re-trigger onChange
    if (!file) return;
    setPickError(null);
    if (!AVATAR_ALLOWED_TYPES.includes(file.type)) {
      setPickError('Choose a PNG, JPEG, WEBP, or GIF image.');
      return;
    }
    if (file.size > AVATAR_MAX_UPLOAD_BYTES) {
      setPickError('That image is larger than 15MB.');
      return;
    }
    setPendingFile(file);
  }

  async function handleCropSave(dataUrl: string) {
    const updated = await updateAvatar(dataUrl);
    onUserUpdated(updated);
    setPendingFile(null);
  }

  async function handleRemove() {
    setIsRemoving(true);
    setRemoveError(null);
    try {
      const updated = await removeAvatar();
      onUserUpdated(updated);
    } catch (error) {
      setRemoveError(error instanceof ApiError ? error.message : 'Could not remove your photo.');
    } finally {
      setIsRemoving(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h2>Profile photo</h2>
          <p>Shown in the sidebar across the platform.</p>
        </div>
      </div>
      <div className="avatar-photo-row">
        <AvatarCircle user={currentUser} size={72} />
        <div className="avatar-photo-actions">
          <div className="avatar-photo-buttons">
            <button type="button" className="secondary-button" onClick={() => fileInputRef.current?.click()}>
              <Camera size={16} aria-hidden />
              Change photo
            </button>
            {currentUser.avatarUrl && (
              <button type="button" className="secondary-button" onClick={() => void handleRemove()} disabled={isRemoving}>
                {isRemoving ? 'Removing…' : 'Remove'}
              </button>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              className="visually-hidden"
              onChange={handleFileChange}
            />
          </div>
          <p className="avatar-photo-hint">PNG, JPEG, WEBP, or GIF, up to 15MB — you'll be able to crop it next.</p>
          {pickError && <p className="inline-error">{pickError}</p>}
          {removeError && <p className="inline-error">{removeError}</p>}
        </div>
      </div>

      {pendingFile && <AvatarCropModal file={pendingFile} onCancel={() => setPendingFile(null)} onSave={handleCropSave} />}
    </div>
  );
}

function PersonalInformationPanel({ currentUser, onUserUpdated }: { currentUser: User; onUserUpdated: (user: User) => void }) {
  const [displayName, setDisplayName] = useState(currentUser.displayName);
  const [isSavingName, setIsSavingName] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSaved, setNameSaved] = useState(false);

  // Keep the field in sync if the account is updated from elsewhere (e.g.
  // a fresh /auth/me fetch on another tab), without clobbering an in-progress edit.
  useEffect(() => {
    setDisplayName(currentUser.displayName);
  }, [currentUser.displayName]);

  async function handleNameSubmit(event: FormEvent) {
    event.preventDefault();
    setNameError(null);
    setNameSaved(false);
    setIsSavingName(true);
    try {
      const updated = await updateProfile({ displayName });
      onUserUpdated(updated);
      setNameSaved(true);
    } catch (error) {
      setNameError(error instanceof ApiError ? error.message : 'Could not update your name.');
    } finally {
      setIsSavingName(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h2>Personal information</h2>
          <p>Your display name and account email.</p>
        </div>
      </div>
      <div className="profile-info-rows">
        <form className="profile-info-row" onSubmit={handleNameSubmit}>
          <div className="profile-info-row-label">
            <strong>Full name</strong>
            <small>Shown across the platform</small>
          </div>
          <div className="profile-info-row-control">
            <input
              type="text"
              value={displayName}
              onChange={(event) => {
                setDisplayName(event.target.value);
                setNameSaved(false);
              }}
              placeholder="Jane Analyst"
            />
            <button type="submit" className="primary-button" disabled={isSavingName || displayName === currentUser.displayName}>
              {isSavingName ? 'Saving…' : 'Save'}
            </button>
          </div>
          {nameSaved && <span className="inline-success">Saved.</span>}
          {nameError && <p className="inline-error">{nameError}</p>}
        </form>

        <div className="profile-info-row">
          <div className="profile-info-row-label">
            <strong>Email address</strong>
            <small>Used to sign in — can't be changed here</small>
          </div>
          <div className="profile-info-row-control">
            <input type="text" value={currentUser.email} disabled readOnly />
          </div>
        </div>

        <div className="profile-info-row">
          <div className="profile-info-row-label">
            <strong>Role</strong>
            <small>Assigned by an owner or admin, in Team below</small>
          </div>
          <div className="profile-info-row-control">
            <RoleBadge role={currentUser.role} />
          </div>
        </div>
      </div>
    </div>
  );
}

function PasswordPanel({ onUserUpdated }: { onUserUpdated: (user: User) => void }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function collapse() {
    setIsExpanded(false);
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setError(null);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSaved(false);
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match.');
      return;
    }
    setIsSaving(true);
    try {
      const updated = await updateProfile({ currentPassword, newPassword });
      onUserUpdated(updated);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not change your password.');
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h2>Password</h2>
          <p>Update your account password.</p>
        </div>
      </div>
      {!isExpanded ? (
        <button type="button" className="secondary-button" onClick={() => setIsExpanded(true)}>
          Change password
        </button>
      ) : (
        <form className="inline-form" onSubmit={handleSubmit}>
          <label>
            Current password
            <input
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
            />
          </label>
          <label>
            New password
            <input
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              placeholder="At least 8 characters"
            />
          </label>
          <label>
            Confirm new password
            <input
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
            />
          </label>
          <div className="password-panel-actions">
            <button type="submit" className="primary-button" disabled={isSaving || !currentPassword || !newPassword}>
              {isSaving ? 'Changing…' : 'Change password'}
            </button>
            <button type="button" className="secondary-button" onClick={collapse} disabled={isSaving}>
              Cancel
            </button>
          </div>
          {saved && <span className="inline-success">Password changed.</span>}
          {error && <p className="inline-error">{error}</p>}
        </form>
      )}
    </div>
  );
}

function ActivityLogPanel() {
  const [entries, setEntries] = useState<ActivityLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async (requestedPage: number) => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await listActivityLog({ limit: ROW_PAGE_SIZE, offset: (requestedPage - 1) * ROW_PAGE_SIZE });
      setEntries(result.entries);
      setTotal(result.total);
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load the activity log.');
      setEntries([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh(page);
  }, [page, refresh]);

  const pageCount = Math.max(1, Math.ceil(total / ROW_PAGE_SIZE));

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h2>Activity log</h2>
          <p>Every account and project action across this deployment — who did what, and when.</p>
        </div>
        <Clock size={20} aria-hidden />
      </div>
      {loadError && <p className="inline-error">{loadError}</p>}
      {!loading && entries.length === 0 && !loadError && <p className="empty-state">Nothing logged yet.</p>}
      <div className="match-list">
        {entries.map((entry) => (
          <div className="match-row" key={entry.entryId}>
            <p className="match-input">{entry.summary}</p>
            <small>
              {entry.actorName}
              {entry.projectName ? ` · ${entry.projectName}` : ''} · {entry.createdAt}
            </small>
          </div>
        ))}
      </div>
      <LimitedRowsControls visibleRows={entries} total={total} page={page} pageCount={pageCount} goToPage={setPage} />
    </div>
  );
}

function StationAliasesPanel() {
  const [aliases, setAliases] = useState<StationAlias[]>([]);
  const limitedAliases = useLimitedRows(aliases);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [aliasName, setAliasName] = useState('');
  const [canonicalName, setCanonicalName] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setAliases(await listStationAliases());
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load station aliases.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setSaveError(null);
    try {
      const created = await createStationAlias(aliasName.trim(), canonicalName.trim());
      // Replaces any existing alias for the same name (see the backend's
      // ON CONFLICT ... DO UPDATE) rather than appending a duplicate row.
      setAliases((current) => [...current.filter((alias) => alias.stationAliasId !== created.stationAliasId), created]);
      setAliasName('');
      setCanonicalName('');
    } catch (error) {
      setSaveError(error instanceof ApiError ? error.message : 'Could not save that alias.');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(alias: StationAlias) {
    setPendingDeleteId(alias.stationAliasId);
    setSaveError(null);
    try {
      await deleteStationAlias(alias.stationAliasId);
      setAliases((current) => current.filter((row) => row.stationAliasId !== alias.stationAliasId));
    } catch (error) {
      setSaveError(error instanceof ApiError ? error.message : 'Could not remove that alias.');
    } finally {
      setPendingDeleteId(null);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h2>Station aliases</h2>
          <p>
            A media-spend upload and a ratings diary often name the same real station differently
            (e.g. "TVC Lagos" vs "Lagos, TV Continental (TVC E)"). Confirm a pairing here once and
            it's applied automatically to every project's matching from then on.
          </p>
        </div>
        <Radio size={20} aria-hidden />
      </div>

      <form className="upload-form" onSubmit={handleCreate}>
        <div className="upload-form-row">
          <label>
            Name as it appears in an upload
            <input
              type="text"
              placeholder="e.g. TVC Lagos"
              value={aliasName}
              onChange={(event) => setAliasName(event.target.value)}
              required
            />
          </label>
          <label>
            Treat as this station
            <input
              type="text"
              placeholder="e.g. Lagos, TV Continental (TVC E)"
              value={canonicalName}
              onChange={(event) => setCanonicalName(event.target.value)}
              required
            />
          </label>
        </div>
        {saveError && <p className="inline-error">{saveError}</p>}
        <button type="submit" className="primary-button" disabled={saving}>
          {saving ? 'Saving…' : 'Save alias'}
        </button>
      </form>

      {loadError && <p className="inline-error">{loadError}</p>}
      {!loading && aliases.length === 0 && !loadError && <p className="empty-state">No station aliases set yet.</p>}
      {aliases.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name as uploaded</th>
                <th>Treated as</th>
                <th>Set by</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {limitedAliases.visibleRows.map((alias) => (
                <tr key={alias.stationAliasId}>
                  <td>{alias.aliasName}</td>
                  <td>{alias.canonicalName}</td>
                  <td>{alias.createdByName}</td>
                  <td>
                    <button
                      type="button"
                      className="icon-button"
                      title="Remove this alias"
                      disabled={pendingDeleteId === alias.stationAliasId}
                      onClick={() => handleDelete(alias)}
                    >
                      <Trash2 size={15} aria-hidden />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <LimitedRowsControls {...limitedAliases} total={aliases.length} />
        </div>
      )}
    </div>
  );
}

export default function SettingsSection({
  currentUser,
  onUserUpdated,
}: {
  currentUser: User;
  onUserUpdated: (user: User) => void;
}) {
  const [tab, setTab] = useState<'profile' | 'activityLog' | 'stationAliases'>('profile');
  const canManageTeam = currentUser.role === 'owner' || currentUser.role === 'admin';
  const [users, setUsers] = useState<User[]>([]);
  const limitedUsers = useLimitedRows(users);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pendingUserId, setPendingUserId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setUsers(await listUsers());
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load the team.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (canManageTeam) void refresh();
  }, [canManageTeam, refresh]);

  async function handleRoleChange(userId: string, role: string) {
    setPendingUserId(userId);
    setActionError(null);
    try {
      const updated = await updateUserRole(userId, role);
      setUsers((current) => current.map((user) => (user.userId === userId ? updated : user)));
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Could not update that role.');
    } finally {
      setPendingUserId(null);
    }
  }

  return (
    <>
      <div className="section-tab-bar" role="tablist" aria-label="Settings view">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'profile'}
          className={tab === 'profile' ? 'primary-button' : 'secondary-button'}
          onClick={() => setTab('profile')}
        >
          Profile
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'activityLog'}
          className={tab === 'activityLog' ? 'primary-button' : 'secondary-button'}
          onClick={() => setTab('activityLog')}
        >
          Activity log
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'stationAliases'}
          className={tab === 'stationAliases' ? 'primary-button' : 'secondary-button'}
          onClick={() => setTab('stationAliases')}
        >
          Station aliases
        </button>
      </div>

      {tab === 'activityLog' ? (
        <ActivityLogPanel />
      ) : tab === 'stationAliases' ? (
        <StationAliasesPanel />
      ) : (
        <>
          <ProfilePhotoPanel currentUser={currentUser} onUserUpdated={onUserUpdated} />
          <PersonalInformationPanel currentUser={currentUser} onUserUpdated={onUserUpdated} />
          <PasswordPanel onUserUpdated={onUserUpdated} />

          {canManageTeam ? (
            <div className="panel">
              <div className="panel-header">
                <div>
                  <h2>Team</h2>
                  <p>{loading ? 'Loading…' : `${users.length} account${users.length === 1 ? '' : 's'} on this deployment`}</p>
                </div>
                <Users size={20} aria-hidden />
              </div>
              {loadError && <p className="inline-error">{loadError}</p>}
              {actionError && <p className="inline-error">{actionError}</p>}
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Email</th>
                      <th>Role</th>
                      <th>Joined</th>
                    </tr>
                  </thead>
                  <tbody>
                    {limitedUsers.visibleRows.map((user) => {
                      // Only an owner can change roles (services/api's
                      // require_role('owner') on PATCH /users/{id}/role); an
                      // admin can see the team but not edit it. An owner also
                      // can't demote themselves — the same rule the API
                      // enforces, mirrored here so the control just looks
                      // disabled instead of the user hitting a 422.
                      const canEditThisRow = currentUser.role === 'owner' && user.userId !== currentUser.userId;
                      return (
                        <tr key={user.userId}>
                          <td>{user.displayName || '—'}</td>
                          <td>{user.email}</td>
                          <td>
                            {canEditThisRow ? (
                              <select
                                value={user.role}
                                disabled={pendingUserId === user.userId}
                                onChange={(event) => handleRoleChange(user.userId, event.target.value)}
                              >
                                {ROLES.map((role) => (
                                  <option value={role} key={role}>
                                    {role}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <RoleBadge role={user.role} />
                            )}
                          </td>
                          <td>{user.createdAt}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <LimitedRowsControls {...limitedUsers} total={users.length} />
              </div>
            </div>
          ) : (
            <div className="panel placeholder-panel">
              <h2>Team management</h2>
              <p>Only an owner or admin can view and manage other accounts on this deployment.</p>
            </div>
          )}
        </>
      )}
    </>
  );
}
