import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Users } from 'lucide-react';
import { ApiError, listUsers, updateProfile, updateUserRole } from '../api/client';
import type { User, UserRole } from '../api/contracts';
import { LimitedRowsControls, useLimitedRows } from '../components/LimitedRows';

const ROLES: UserRole[] = ['owner', 'admin', 'member'];

function RoleBadge({ role }: { role: UserRole }) {
  return <span className={`status status-${role === 'owner' ? 'complete' : role === 'admin' ? 'review' : 'setup'}`}>{role}</span>;
}

function ProfilePanel({ currentUser, onUserUpdated }: { currentUser: User; onUserUpdated: (user: User) => void }) {
  const [displayName, setDisplayName] = useState(currentUser.displayName);
  const [isSavingName, setIsSavingName] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSaved, setNameSaved] = useState(false);

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isSavingPassword, setIsSavingPassword] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSaved, setPasswordSaved] = useState(false);

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

  async function handlePasswordSubmit(event: FormEvent) {
    event.preventDefault();
    setPasswordError(null);
    setPasswordSaved(false);
    if (newPassword !== confirmPassword) {
      setPasswordError('New password and confirmation do not match.');
      return;
    }
    setIsSavingPassword(true);
    try {
      const updated = await updateProfile({ currentPassword, newPassword });
      onUserUpdated(updated);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setPasswordSaved(true);
    } catch (error) {
      setPasswordError(error instanceof ApiError ? error.message : 'Could not change your password.');
    } finally {
      setIsSavingPassword(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h2>Your account</h2>
          <p>Signed in as {currentUser.email}</p>
        </div>
      </div>
      <dl className="project-meta">
        <div>
          <dt>Role</dt>
          <dd>
            <RoleBadge role={currentUser.role} />
          </dd>
        </div>
        <div>
          <dt>Member since</dt>
          <dd>{currentUser.createdAt}</dd>
        </div>
      </dl>

      <form className="inline-form" onSubmit={handleNameSubmit}>
        <label>
          Name
          <input
            type="text"
            value={displayName}
            onChange={(event) => {
              setDisplayName(event.target.value);
              setNameSaved(false);
            }}
            placeholder="Jane Analyst"
          />
        </label>
        <button type="submit" className="secondary-button" disabled={isSavingName || displayName === currentUser.displayName}>
          {isSavingName ? 'Saving…' : 'Save name'}
        </button>
        {nameSaved && <span className="inline-success">Saved.</span>}
        {nameError && <p className="inline-error">{nameError}</p>}
      </form>

      <form className="inline-form" onSubmit={handlePasswordSubmit}>
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
        <button
          type="submit"
          className="secondary-button"
          disabled={isSavingPassword || !currentPassword || !newPassword}
        >
          {isSavingPassword ? 'Changing…' : 'Change password'}
        </button>
        {passwordSaved && <span className="inline-success">Password changed.</span>}
        {passwordError && <p className="inline-error">{passwordError}</p>}
      </form>
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
      <ProfilePanel currentUser={currentUser} onUserUpdated={onUserUpdated} />

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
  );
}
