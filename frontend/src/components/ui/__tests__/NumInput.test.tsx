import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import NumInput from '../NumInput'

describe('NumInput', () => {
  it('should render with initial value', () => {
    render(<NumInput value={42} onChange={vi.fn()} />)

    const input = screen.getByRole('spinbutton')
    expect(input).toHaveValue(42)
  })

  it('should render increase and decrease buttons', () => {
    render(<NumInput value={0} onChange={vi.fn()} />)

    expect(screen.getByLabelText('Increase value')).toBeInTheDocument()
    expect(screen.getByLabelText('Decrease value')).toBeInTheDocument()
  })

  it('should call onChange when user types a numeric value', () => {
    const onChange = vi.fn()
    render(<NumInput value={0} onChange={onChange} />)

    const input = screen.getByRole('spinbutton')
    fireEvent.change(input, { target: { value: '25' } })

    expect(onChange).toHaveBeenCalled()
  })

  it('should apply min and max attributes to the input', () => {
    render(<NumInput value={5} min={0} max={10} onChange={vi.fn()} />)

    const input = screen.getByRole('spinbutton')
    expect(input).toHaveAttribute('min', '0')
    expect(input).toHaveAttribute('max', '10')
  })

  it('should apply step attribute to the input', () => {
    render(<NumInput value={0} step={0.5} onChange={vi.fn()} />)

    const input = screen.getByRole('spinbutton')
    expect(input).toHaveAttribute('step', '0.5')
  })

  it('should trigger input event when increase button is clicked', () => {
    // The nudge function uses the native value setter and dispatches an
    // input event. We listen for that event to verify the nudge fires.
    const inputEventSpy = vi.fn()
    const { container } = render(<NumInput value={5} step={1} onChange={vi.fn()} />)

    const input = container.querySelector('input') as HTMLInputElement
    input.addEventListener('input', inputEventSpy)

    const increaseBtn = screen.getByLabelText('Increase value')
    fireEvent.pointerDown(increaseBtn)

    expect(inputEventSpy).toHaveBeenCalled()
  })

  it('should trigger input event when decrease button is clicked', () => {
    const inputEventSpy = vi.fn()
    const { container } = render(<NumInput value={5} step={1} onChange={vi.fn()} />)

    const input = container.querySelector('input') as HTMLInputElement
    input.addEventListener('input', inputEventSpy)

    const decreaseBtn = screen.getByLabelText('Decrease value')
    fireEvent.pointerDown(decreaseBtn)

    expect(inputEventSpy).toHaveBeenCalled()
  })

  it('should respect min constraint when nudging down', () => {
    // When value=min, nudging down should keep value at min
    const inputEventSpy = vi.fn()
    const { container } = render(<NumInput value={0} step={1} min={0} onChange={vi.fn()} />)

    const input = container.querySelector('input') as HTMLInputElement
    input.addEventListener('input', (e) => {
      inputEventSpy((e.target as HTMLInputElement).value)
    })

    const decreaseBtn = screen.getByLabelText('Decrease value')
    fireEvent.pointerDown(decreaseBtn)

    // The nudge should have set value to 0 (clamped to min)
    expect(inputEventSpy).toHaveBeenCalledWith('0')
  })

  it('should respect max constraint when nudging up', () => {
    const inputEventSpy = vi.fn()
    const { container } = render(<NumInput value={10} step={1} max={10} onChange={vi.fn()} />)

    const input = container.querySelector('input') as HTMLInputElement
    input.addEventListener('input', (e) => {
      inputEventSpy((e.target as HTMLInputElement).value)
    })

    const increaseBtn = screen.getByLabelText('Increase value')
    fireEvent.pointerDown(increaseBtn)

    // The nudge should have set value to 10 (clamped to max)
    expect(inputEventSpy).toHaveBeenCalledWith('10')
  })

  it('should use step of 1 when step is not provided', () => {
    const inputEventSpy = vi.fn()
    const { container } = render(<NumInput value={5} onChange={vi.fn()} />)

    const input = container.querySelector('input') as HTMLInputElement
    input.addEventListener('input', (e) => {
      inputEventSpy((e.target as HTMLInputElement).value)
    })

    const increaseBtn = screen.getByLabelText('Increase value')
    fireEvent.pointerDown(increaseBtn)

    // Default step=1, so 5+1=6
    expect(inputEventSpy).toHaveBeenCalledWith('6')
  })

  it('should apply wrapClassName to the wrapper', () => {
    const { container } = render(<NumInput value={0} wrapClassName="custom-wrap" onChange={vi.fn()} />)

    const wrapper = container.firstChild as HTMLElement
    expect(wrapper.className).toContain('custom-wrap')
  })
})
