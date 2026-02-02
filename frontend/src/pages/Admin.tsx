/**
 * Admin Dashboard Page.
 *
 * System monitoring and management for administrators.
 */

import { Routes, Route, Link, useLocation } from 'react-router-dom';
import { SystemHealth } from '../components/SystemHealth';
import { UserManagement } from '../components/UserManagement';
import { AuditLogViewer } from '../components/AuditLogViewer';
import { useAuth } from '../context/AuthContext';

function AdminNav() {
  const location = useLocation();

  const navItems = [
    { path: '/admin', label: 'System Health', exact: true },
    { path: '/admin/users', label: 'User Management' },
    { path: '/admin/audit', label: 'Audit Logs' },
  ];

  const isActive = (path: string, exact?: boolean) => {
    if (exact) {
      return location.pathname === path;
    }
    return location.pathname.startsWith(path);
  };

  return (
    <div className="bg-white rounded-lg shadow mb-6">
      <nav className="flex border-b border-gray-200">
        {navItems.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className={`px-6 py-4 text-sm font-medium border-b-2 -mb-px ${
              isActive(item.path, item.exact)
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}

export function Admin() {
  const { user } = useAuth();

  // Check if user is admin
  if (!user?.is_admin) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-4">Access Denied</h1>
          <p className="text-gray-600 mb-4">
            You don't have permission to access the admin dashboard.
          </p>
          <Link
            to="/dashboard"
            className="text-indigo-600 hover:text-indigo-500"
          >
            Return to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <div className="bg-indigo-600 text-white py-4">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold">Admin Dashboard</h1>
              <p className="text-indigo-200 text-sm">System Management</p>
            </div>
            <Link
              to="/dashboard"
              className="px-4 py-2 bg-indigo-500 rounded-md hover:bg-indigo-400 text-sm"
            >
              Back to Dashboard
            </Link>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
        <AdminNav />

        <Routes>
          <Route index element={<SystemHealth />} />
          <Route path="users" element={<UserManagement />} />
          <Route path="audit" element={<AuditLogViewer />} />
        </Routes>
      </div>
    </div>
  );
}
