import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import type { User } from '../types'

export default function AdminUsers() {
  const { t } = useTranslation()
  const [users, setUsers] = useState<User[]>([])
  const [showForm, setShowForm] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('user')

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

  const deleteUser = async (id: number) => {
    if (!confirm('Delete user?')) return
    await api.delete(`/users/${id}`)
    loadUsers()
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">{t('nav.admin')} - Users</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700"
        >
          + New User
        </button>
      </div>

      {showForm && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 mb-6 max-w-lg">
          <div className="space-y-4">
            <input type="text" placeholder="Username" value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
            <input type="password" placeholder="Password (min 8 chars)" value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
            <input type="email" placeholder="Email (optional)" value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
            <select value={role} onChange={(e) => setRole(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white">
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
            <div className="flex gap-2">
              <button onClick={createUser}
                className="px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700">
                Create
              </button>
              <button onClick={() => setShowForm(false)}
                className="px-4 py-2 bg-gray-700 text-gray-300 rounded hover:bg-gray-600">
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left p-3 text-gray-400">ID</th>
              <th className="text-left p-3 text-gray-400">Username</th>
              <th className="text-left p-3 text-gray-400">Email</th>
              <th className="text-left p-3 text-gray-400">Role</th>
              <th className="text-left p-3 text-gray-400">Status</th>
              <th className="text-right p-3 text-gray-400">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} className="border-b border-gray-800/50">
                <td className="p-3 text-gray-500">{user.id}</td>
                <td className="p-3 text-white font-medium">{user.username}</td>
                <td className="p-3 text-gray-400">{user.email || '--'}</td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    user.role === 'admin' ? 'bg-purple-900/30 text-purple-400' : 'bg-gray-800 text-gray-400'
                  }`}>
                    {user.role}
                  </span>
                </td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    user.is_active ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
                  }`}>
                    {user.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="p-3 text-right">
                  <div className="flex gap-2 justify-end">
                    <button onClick={() => toggleActive(user)}
                      className="px-2 py-1 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700">
                      {user.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                    <button onClick={() => deleteUser(user.id)}
                      className="px-2 py-1 text-xs bg-red-900/20 text-red-400 rounded hover:bg-red-900/30">
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
