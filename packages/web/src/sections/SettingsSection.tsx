import { useCallback, useEffect, useState } from 'react';
import { Users } from 'lucide-react';
import { ApiError, listUsers, updateUserRole } from '../api/client';
import type { User, UserRole } from '../api/contracts';

const ROLES: UserRole[] = ['owner', 'admin', 'member'];

function RoleBadge({ role }: { role: UserRole }) {
  return <span className={`status status-${role === 'owner' ? 'complete' : role === 'admin' ? 'review' : 'setup'}`}>{role}</span>;
}

export default function SettingsSection({ currentUser }: { currentUser: User }) {
  const canManageTeam = currentUser.role === 'owner' || currentUser.role === 'admin';
  const [users, setUsers] = useState<User[]>([]);
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
      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>Your account</h2>
            <p>Signed in as {currentUser.email}</p>
          </div>
        </div>
        <dl className="project-meta">
          <div>
            <dt>Name</dt>
            <dd>{currentUser.displayName || '—'}</dd>
          </div>
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
      </div>

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
                {users.map((user) => {
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
