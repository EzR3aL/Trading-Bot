import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Check } from 'lucide-react'
import { useThemeStore } from '../../stores/themeStore'

interface Option {
  value: string
  label: string
}

interface Props {
  value: string
  onChange: (value: string) => void
  options: Option[]
  ariaLabel?: string
}

export default function FilterDropdown({ value, onChange, options, ariaLabel }: Props) {
  const theme = useThemeStore((s) => s.theme)
  const isLight = theme === 'light'
  const [isOpen, setIsOpen] = useState(false)
  const [highlightIndex, setHighlightIndex] = useState(-1)
  const ref = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const selectedLabel = options.find(o => o.value === value)?.label || options[0]?.label || ''

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false)
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [isOpen])

  // Reset highlight when dropdown opens/closes
  useEffect(() => {
    if (isOpen) {
      // Highlight the currently selected option when opening
      const idx = options.findIndex(o => o.value === value)
      setHighlightIndex(idx >= 0 ? idx : 0)
    } else {
      setHighlightIndex(-1)
    }
  }, [isOpen, options, value])

  // Scroll highlighted option into view
  useEffect(() => {
    if (!isOpen || highlightIndex < 0 || !listRef.current) return
    const items = listRef.current.querySelectorAll<HTMLElement>('[role="option"]')
    if (items[highlightIndex]) {
      items[highlightIndex].scrollIntoView({ block: 'nearest' })
    }
  }, [highlightIndex, isOpen])

  const select = (val: string) => {
    onChange(val)
    setIsOpen(false)
  }

  const handleListKeyDown = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown': {
        e.preventDefault()
        setHighlightIndex(prev => (prev < options.length - 1 ? prev + 1 : 0))
        break
      }
      case 'ArrowUp': {
        e.preventDefault()
        setHighlightIndex(prev => (prev > 0 ? prev - 1 : options.length - 1))
        break
      }
      case 'Home': {
        e.preventDefault()
        setHighlightIndex(0)
        break
      }
      case 'End': {
        e.preventDefault()
        setHighlightIndex(options.length - 1)
        break
      }
      case 'Enter':
      case ' ': {
        e.preventDefault()
        if (highlightIndex >= 0 && highlightIndex < options.length) {
          select(options[highlightIndex].value)
        }
        break
      }
    }
  }

  return (
    <div className="relative inline-flex" ref={ref}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-label={ariaLabel}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        className={`filter-select inline-flex items-center gap-2 cursor-pointer whitespace-nowrap ${
          isOpen
            ? isLight
              ? '!border-emerald-400/40 !bg-white ring-1 ring-emerald-400/30'
              : '!border-emerald-500/50 !bg-white/[0.07] ring-1 ring-emerald-500/30'
            : ''
        }`}
      >
        <span>{selectedLabel}</span>
        <ChevronDown
          size={13}
          className={`transition-transform duration-200 ${isOpen ? 'rotate-180' : ''} ${
            isLight ? 'text-gray-400' : 'text-gray-500'
          }`}
        />
      </button>

      {isOpen && (
        <div className={`absolute top-full mt-1.5 left-0 z-50 min-w-full rounded-xl border shadow-2xl backdrop-blur-xl animate-in ${
          isLight
            ? 'bg-white border-gray-200 shadow-gray-200/50'
            : 'bg-[#141a2a]/95 border-white/10 shadow-black/60'
        }`}>
          <div
            ref={listRef}
            className="py-1.5 max-h-60 overflow-y-auto"
            role="listbox"
            aria-label={ariaLabel}
            tabIndex={0}
            onKeyDown={handleListKeyDown}
          >
            {options.map((opt, idx) => {
              const isActive = opt.value === value
              const isHighlighted = idx === highlightIndex
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  onClick={() => select(opt.value)}
                  onMouseEnter={() => setHighlightIndex(idx)}
                  className={`w-full flex items-center justify-between gap-4 px-3.5 py-2 text-sm transition-colors ${
                    isHighlighted
                      ? isLight
                        ? 'bg-emerald-50 text-emerald-700'
                        : 'bg-emerald-500/15 text-emerald-400'
                      : isActive
                        ? isLight
                          ? 'bg-emerald-50/60 text-emerald-700'
                          : 'bg-emerald-500/10 text-emerald-400'
                        : isLight
                          ? 'text-gray-700 hover:bg-gray-50'
                          : 'text-gray-300 hover:bg-white/5'
                  }`}
                >
                  <span className="whitespace-nowrap">{opt.label}</span>
                  {isActive && <Check size={14} className={isLight ? 'text-emerald-600' : 'text-emerald-400'} />}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
