import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Shield, ShieldOff, LayoutGrid, List, Trash2, UserCheck, UserX } from 'lucide-react'
import api from '../api/client'
import FilterDropdown from '../components/ui/FilterDropdown'
import { useAuthStore } from '../stores/authStore'
import type { User } from '../types'

export default function AdminUsers() {
  const { t } = useTranslation()
  const currentUser = useAuthStore((s) => s.user)
  const [users, setUsers] = useState<User[]>([])
  const [showForm, setShowForm] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('user')
  const [view, setView] = useState<'grid' | 'list'>('grid')

  const loadUsers = async () => {
    try {
      const res = await api.get('/users')
      setUsers(res.data)
    } catch { /* ignore */ }
  }

  useEffect(() => { loadUsers() }, [])

  const createUser = async () => {
    try {
      await api.post('/users', { username, password, email: email || null, role, language: 'de' })
      setShowForm(false)
      setUsername(''); setPassword(''); setEmail(''); setRole('user')
      loadUsers()
    } catch { /* ignore */ }
  }

  const toggleActive = async (user: User) => {
    await api.put(`/users/${user.id}`, { is_active: !user.is_active })
    loadUsers()
  }

  const toggleRole = async (user: User) => {
    if (user.id === currentUser?.id) {
      alert(t('admin.cannotDemoteSelf'))
      return
    }
    if (!confirm(t('admin.confirmRoleChange'))) return
    const newRole = user.role === 'admin' ? 'user' : 'admin'
    await api.put(`/users/${user.id}`, { role: newRole })
    loadUsers()
  }

  const deleteUser = async (id: number) => {
    if (!confirm(t('admin.deleteUser'))) return
    await api.delete(`/users/${id}`)
    loadUsers()
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-2xl font-bold text-white">{t('nav.admin')} - {t('admin.users')}</h1>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-white/10 overflow-hidden">
            <button
              onClick={() => setView('grid')}
              className={`p-1.5 transition-colors ${view === 'grid' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
            >
              <LayoutGrid size={15} />
            </button>
            <button
              onClick={() => setView('list')}
              className={`p-1.5 transition-colors ${view === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
            >
              <List size={15} />
            </button>
          </div>
          <button
            onClick={() => setShowForm(!showForm)}
            className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
          >
            + {t('admin.newUser')}
          </button>
        </div>
      </div>

      {showForm && (
        <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5 mb-5 max-w-lg">
          <h2 className="text-sm font-semibold text-white mb-3">{t('admin.newUser')}</h2>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <input type="text" placeholder="Username" value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="filter-select w-full text-sm" />
              <input type="password" placeholder="Password (min 8)" value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="filter-select w-full text-sm" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <input type="email" placeholder="Email (optional)" value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="filter-select w-full text-sm" />
              <FilterDropdown
                value={role}
                onChange={val => setRole(val)}
                options={[
                  { value: 'user', label: 'User' },
                  { value: 'admin', label: 'Admin' },
                ]}
                ariaLabel="Role"
              />
            </div>
            <div className="flex gap-2 pt-1">
              <button onClick={createUser}
                className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors">
                Create
              </button>
              <button onClick={() => setShowForm(false)}
                className="px-3 py-1.5 text-sm bg-white/5 border border-white/10 text-gray-300 rounded-lg hover:bg-white/10 transition-colors">
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Grid View */}
      {view === 'grid' ? (
        <div className="grid grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-2.5">
          {users.map((user) => (
            <div key={user.id}
              className={`border bg-white/[0.03] rounded-xl px-3 py-2.5 hover:bg-white/[0.05] transition-colors ${
                user.is_active ? 'border-white/10' : 'border-red-500/20'
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 ${
                  user.role === 'admin' ? 'bg-purple-900/40 text-purple-400' : 'bg-white/5 text-gray-500'
                }`}>
                  {user.username.charAt(0).toUpperCase()}
                </div>
                <span className="text-sm font-medium text-white truncate">{user.username}</span>
                <span className={`ml-auto text-[10px] px-1.5 py-0.5 rounded font-medium flex-shrink-0 ${
                  user.role === 'admin' ? 'bg-purple-900/30 text-purple-400' : 'bg-white/5 text-gray-500'
                }`}>{user.role.charAt(0).toUpperCase() + user.role.slice(1)}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded flex-shrink-0 ${
                  user.is_active ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
                }`}>{user.is_active ? t('admin.active') : t('admin.inactive')}</span>
              </div>
              {user.email && (
                <div className="text-xs text-gray-500 truncate mb-1.5 pl-8">{user.email}</div>
              )}
              <div className="flex gap-1.5 pt-1.5 border-t border-white/5">
                <button onClick={() => toggleRole(user)} disabled={user.id === currentUser?.id}
                  className={`p-1 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                    user.role === 'admin' ? 'text-purple-400 hover:bg-purple-900/30' : 'text-blue-400 hover:bg-blue-900/30'
                  }`} title={user.id === currentUser?.id ? t('admin.cannotDemoteSelf') : (user.role === 'admin' ? t('admin.makeUser') : t('admin.makeAdmin'))}>
                  {user.role === 'admin' ? <ShieldOff size={14} /> : <Shield size={14} />}
                </button>
                <button onClick={() => toggleActive(user)}
                  title={user.is_active ? t('admin.deactivate') : t('admin.activate')}
                  className="p-1 text-gray-500 hover:text-gray-300 transition-colors">
                  {user.is_active ? <UserX size={14} /> : <UserCheck size={14} />}
                </button>
                <button onClick={() => deleteUser(user.id)}
                  title={t('admin.deleteUser')}
                  className="p-1 text-red-400/50 hover:text-red-400 transition-colors ml-auto">
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* List View */
        <div className="space-y-1.5">
          {users.map((user) => (
            <div key={user.id}
              className={`border bg-white/[0.03] rounded-lg flex items-center gap-3 px-3 py-2 hover:bg-white/[0.05] transition-colors ${
                user.is_active ? 'border-white/10' : 'border-red-500/20'
              }`}
            >
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 ${
                user.role === 'admin' ? 'bg-purple-900/40 text-purple-400' : 'bg-white/5 text-gray-500'
              }`}>
                {user.username.charAt(0).toUpperCase()}
              </div>
              <span className="text-sm font-medium text-white whitespace-nowrap">{user.username}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                user.role === 'admin' ? 'bg-purple-900/30 text-purple-400' : 'bg-white/5 text-gray-500'
              }`}>
                {user.role.charAt(0).toUpperCase() + user.role.slice(1)}
              </span>
              {user.email && (
                <span className="text-xs text-gray-500 truncate hidden lg:block">{user.email}</span>
              )}
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                user.is_active ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
              }`}>
                {user.is_active ? t('admin.active') : t('admin.inactive')}
              </span>

              <div className="flex gap-1.5 ml-auto flex-shrink-0">
                <button
                  onClick={() => toggleRole(user)}
                  disabled={user.id === currentUser?.id}
                  className={`p-1 rounded-md transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                    user.role === 'admin'
                      ? 'text-purple-400 hover:bg-purple-900/30'
                      : 'text-blue-400 hover:bg-blue-900/30'
                  }`}
                  title={user.id === currentUser?.id ? t('admin.cannotDemoteSelf') : (user.role === 'admin' ? t('admin.makeUser') : t('admin.makeAdmin'))}
                >
                  {user.role === 'admin' ? <ShieldOff size={13} /> : <Shield size={13} />}
                </button>
                <button onClick={() => toggleActive(user)}
                  title={user.is_active ? t('admin.deactivate') : t('admin.activate')}
                  className="p-1 text-gray-500 hover:text-gray-300 transition-colors">
                  {user.is_active ? <UserX size={13} /> : <UserCheck size={13} />}
                </button>
                <button onClick={() => deleteUser(user.id)}
                  title={t('admin.deleteUser')}
                  className="p-1 text-red-400/50 hover:text-red-400 transition-colors">
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {users.length === 0 && (
        <div className="text-center text-gray-500 py-12 text-sm">
          Keine Benutzer vorhanden.
        </div>
      )}
    </div>
  )
}
