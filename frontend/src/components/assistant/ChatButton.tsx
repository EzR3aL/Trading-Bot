import { useEffect } from 'react'
import { MessageCircle, X } from 'lucide-react'
import { useAssistantStore } from '../../stores/assistantStore'

export default function ChatButton() {
  const { isOpen, isAvailable, toggle, checkAvailability } = useAssistantStore()

  useEffect(() => {
    checkAvailability()
  }, [checkAvailability])

  // Don't render if assistant is not available
  if (isAvailable === false) return null
  // Don't render while checking availability
  if (isAvailable === null) return null

  return (
    <button
      onClick={toggle}
      className={`fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full shadow-lg flex items-center justify-center transition-all duration-200 ${
        isOpen
          ? 'bg-gray-700 hover:bg-gray-600 rotate-0'
          : 'bg-primary-600 hover:bg-primary-700 hover:scale-105'
      }`}
      title="Trading Assistant"
    >
      {isOpen ? (
        <X size={22} className="text-white" />
      ) : (
        <MessageCircle size={22} className="text-white" />
      )}
    </button>
  )
}
