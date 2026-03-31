import { useRef, useCallback } from 'react'

interface NumInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  wrapClassName?: string
}

export default function NumInput({ wrapClassName, className, step, min, max, value, onChange, ...rest }: NumInputProps) {
  const ref = useRef<HTMLInputElement>(null)

  const nudge = useCallback((dir: 1 | -1) => {
    const input = ref.current
    if (!input) return
    const s = Number(step) || 1
    const cur = parseFloat(input.value) || 0
    let next = Math.round((cur + dir * s) * 1e8) / 1e8
    if (min !== undefined) next = Math.max(Number(min), next)
    if (max !== undefined) next = Math.min(Number(max), next)
    const nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    nativeSet.call(input, String(next))
    input.dispatchEvent(new Event('input', { bubbles: true }))
  }, [step, min, max])

  return (
    <span className={`num-input-wrap ${wrapClassName || ''}`}>
      <input ref={ref} type="number" className={className} step={step} min={min} max={max} value={value} onChange={onChange} {...rest} />
      <span className="num-arrows">
        <span className="num-arrow num-arrow-up" onPointerDown={() => nudge(1)} role="button" tabIndex={0} aria-label="Increase value">
          <svg viewBox="0 0 12 12" fill="none" stroke="currentColor"><path d="M3 7.5 6 4.5 9 7.5" /></svg>
        </span>
        <span className="num-arrow num-arrow-down" onPointerDown={() => nudge(-1)} role="button" tabIndex={0} aria-label="Decrease value">
          <svg viewBox="0 0 12 12" fill="none" stroke="currentColor"><path d="M3 4.5 6 7.5 9 4.5" /></svg>
        </span>
      </span>
    </span>
  )
}
