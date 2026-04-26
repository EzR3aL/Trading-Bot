/**
 * Spinner shown while a lazily-loaded admin tab subpage hydrates.
 */
export default function TabLoader() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}
