import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Calendar } from 'lucide-react'
import { useThemeStore } from '../../stores/themeStore'

interface Props {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  label?: string
  minDate?: string  // YYYY-MM-DD
  maxDate?: string  // YYYY-MM-DD
}

const WEEKDAYS_DE = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
const MONTHS_DE = [
  'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
  'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
]

function getDaysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate()
}

function getFirstDayOfWeek(year: number, month: number) {
  const day = new Date(year, month, 1).getDay()
  return day === 0 ? 6 : day - 1 // Monday = 0
}

export default function DatePicker({ value, onChange, placeholder, label, minDate, maxDate }: Props) {
  const theme = useThemeStore((s) => s.theme)
  const isLight = theme === 'light'
  const [isOpen, setIsOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const today = new Date()
  const parsed = value ? new Date(value + 'T00:00:00') : null
  const [viewYear, setViewYear] = useState(parsed?.getFullYear() ?? today.getFullYear())
  const [viewMonth, setViewMonth] = useState(parsed?.getMonth() ?? today.getMonth())

  useEffect(() => {
    if (isOpen && parsed) {
      setViewYear(parsed.getFullYear())
      setViewMonth(parsed.getMonth())
    }
  }, [isOpen])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const daysInMonth = getDaysInMonth(viewYear, viewMonth)
  const firstDay = getFirstDayOfWeek(viewYear, viewMonth)

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(viewYear - 1) }
    else setViewMonth(viewMonth - 1)
  }

  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(viewYear + 1) }
    else setViewMonth(viewMonth + 1)
  }

  const selectDay = (day: number) => {
    const m = String(viewMonth + 1).padStart(2, '0')
    const d = String(day).padStart(2, '0')
    onChange(`${viewYear}-${m}-${d}`)
    setIsOpen(false)
  }

  const clearValue = () => {
    onChange('')
    setIsOpen(false)
  }

  const isToday = (day: number) =>
    viewYear === today.getFullYear() && viewMonth === today.getMonth() && day === today.getDate()

  const isSelected = (day: number) =>
    parsed && viewYear === parsed.getFullYear() && viewMonth === parsed.getMonth() && day === parsed.getDate()

  const isDisabledDay = (day: number) => {
    const dateStr = `${viewYear}-${String(viewMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
    if (minDate && dateStr < minDate) return true
    if (maxDate && dateStr > maxDate) return true
    return false
  }

  const displayValue = parsed
    ? parsed.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' })
    : ''

  // Previous month trailing days
  const prevMonthDays = getDaysInMonth(viewYear, viewMonth - 1)
  const trailingDays = Array.from({ length: firstDay }, (_, i) => prevMonthDays - firstDay + 1 + i)

  // Next month leading days
  const totalCells = firstDay + daysInMonth
  const leadingDays = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7)

  return (
    <div className="relative inline-flex items-center" ref={ref}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={`filter-select inline-flex items-center gap-2 cursor-pointer ${
          isOpen ? (isLight ? 'border-emerald-400/40 bg-white ring-1 ring-emerald-400/30' : '!border-emerald-500/50 !bg-white/[0.07] ring-1 ring-emerald-500/30') : ''
        }`}
      >
        <Calendar size={13} className={isLight ? 'text-gray-400' : 'text-gray-500'} />
        {label && !displayValue && <span className={isLight ? 'text-gray-400' : 'text-gray-500'}>{label}</span>}
        {displayValue && (
          <>
            {label && <span className={isLight ? 'text-gray-400' : 'text-gray-500'}>{label}:</span>}
            <span className="text-white">{displayValue}</span>
          </>
        )}
        {!label && !displayValue && <span className={isLight ? 'text-gray-400' : 'text-gray-500'}>{placeholder || 'Datum...'}</span>}
      </button>

      {isOpen && (
        <div className={`absolute top-full mt-2 z-50 w-[280px] rounded-xl border shadow-2xl backdrop-blur-xl animate-in ${
          isLight
            ? 'bg-white border-gray-200 shadow-gray-200/50'
            : 'bg-[#141a2a]/95 border-white/10 shadow-black/60'
        }`}>
          {/* Header: Month/Year Navigation */}
          <div className="flex items-center justify-between px-4 pt-4 pb-2">
            <button
              type="button"
              onClick={prevMonth}
              className={`p-1.5 rounded-lg transition-colors ${
                isLight ? 'hover:bg-gray-100 text-gray-500' : 'hover:bg-white/10 text-gray-400'
              }`}
            >
              <ChevronLeft size={16} />
            </button>
            <span className={`text-sm font-semibold tracking-wide ${isLight ? 'text-gray-800' : 'text-white'}`}>
              {MONTHS_DE[viewMonth]} {viewYear}
            </span>
            <button
              type="button"
              onClick={nextMonth}
              className={`p-1.5 rounded-lg transition-colors ${
                isLight ? 'hover:bg-gray-100 text-gray-500' : 'hover:bg-white/10 text-gray-400'
              }`}
            >
              <ChevronRight size={16} />
            </button>
          </div>

          {/* Weekday Headers */}
          <div className="grid grid-cols-7 px-3 pb-1">
            {WEEKDAYS_DE.map((d) => (
              <div key={d} className={`text-center text-[10px] font-medium py-1 ${
                isLight ? 'text-gray-400' : 'text-gray-500'
              }`}>
                {d}
              </div>
            ))}
          </div>

          {/* Day Grid */}
          <div className="grid grid-cols-7 px-3 pb-3 gap-0.5">
            {/* Previous month trailing days */}
            {trailingDays.map((day) => (
              <div key={`prev-${day}`} className={`text-center text-xs py-1.5 rounded-lg ${
                isLight ? 'text-gray-300' : 'text-gray-700'
              }`}>
                {day}
              </div>
            ))}

            {/* Current month days */}
            {Array.from({ length: daysInMonth }, (_, i) => i + 1).map((day) => {
              const disabled = isDisabledDay(day)
              return (
                <button
                  key={day}
                  type="button"
                  onClick={() => !disabled && selectDay(day)}
                  disabled={disabled}
                  className={`text-center text-xs py-1.5 rounded-lg font-medium transition-all duration-150 ${
                    disabled
                      ? isLight
                        ? 'text-gray-300 cursor-not-allowed'
                        : 'text-gray-700 cursor-not-allowed'
                      : isSelected(day)
                        ? 'bg-emerald-500 text-white shadow-lg shadow-emerald-500/30'
                        : isToday(day)
                          ? isLight
                            ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200'
                            : 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30'
                          : isLight
                            ? 'text-gray-700 hover:bg-gray-100'
                            : 'text-gray-300 hover:bg-white/10'
                  }`}
                >
                  {day}
                </button>
              )
            })}

            {/* Next month leading days */}
            {Array.from({ length: leadingDays }, (_, i) => i + 1).map((day) => (
              <div key={`next-${day}`} className={`text-center text-xs py-1.5 rounded-lg ${
                isLight ? 'text-gray-300' : 'text-gray-700'
              }`}>
                {day}
              </div>
            ))}
          </div>

          {/* Footer */}
          <div className={`flex items-center justify-between px-4 py-2.5 border-t ${
            isLight ? 'border-gray-100' : 'border-white/5'
          }`}>
            {value ? (
              <button
                type="button"
                onClick={clearValue}
                className={`text-xs transition-colors ${
                  isLight ? 'text-gray-400 hover:text-red-500' : 'text-gray-500 hover:text-red-400'
                }`}
              >
                Löschen
              </button>
            ) : <span />}
            <button
              type="button"
              onClick={() => {
                const m = String(today.getMonth() + 1).padStart(2, '0')
                const d = String(today.getDate()).padStart(2, '0')
                onChange(`${today.getFullYear()}-${m}-${d}`)
                setIsOpen(false)
              }}
              className="text-xs text-emerald-400 hover:text-emerald-300 font-medium transition-colors"
            >
              Heute
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
