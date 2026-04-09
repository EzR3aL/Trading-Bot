import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ConfirmModal from '../ConfirmModal'

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback: string) => fallback || key,
  }),
}))

const defaultProps = {
  open: true,
  title: 'Delete Bot',
  message: 'Are you sure you want to delete this bot?',
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
}

describe('ConfirmModal', () => {
  it('should render when open is true', () => {
    render(<ConfirmModal {...defaultProps} />)

    expect(screen.getByText('Delete Bot')).toBeInTheDocument()
    expect(screen.getByText('Are you sure you want to delete this bot?')).toBeInTheDocument()
  })

  it('should not render when open is false', () => {
    const { container } = render(<ConfirmModal {...defaultProps} open={false} />)

    expect(container.firstChild).toBeNull()
  })

  it('should have aria-modal attribute', () => {
    render(<ConfirmModal {...defaultProps} />)

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
  })

  it('should have aria-labelledby pointing to the title', () => {
    render(<ConfirmModal {...defaultProps} />)

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-labelledby', 'confirm-title')
    expect(screen.getByText('Delete Bot').id).toBe('confirm-title')
  })

  it('should call onConfirm when confirm button is clicked', () => {
    const onConfirm = vi.fn()
    render(<ConfirmModal {...defaultProps} onConfirm={onConfirm} />)

    fireEvent.click(screen.getByText('Confirm'))

    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('should call onCancel when cancel button is clicked', () => {
    const onCancel = vi.fn()
    render(<ConfirmModal {...defaultProps} onCancel={onCancel} />)

    fireEvent.click(screen.getByText('Cancel'))

    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('should call onCancel when close (X) button is clicked', () => {
    const onCancel = vi.fn()
    render(<ConfirmModal {...defaultProps} onCancel={onCancel} />)

    fireEvent.click(screen.getByLabelText('Close'))

    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('should call onCancel when backdrop is clicked', () => {
    const onCancel = vi.fn()
    render(<ConfirmModal {...defaultProps} onCancel={onCancel} />)

    // The backdrop is the first child div with bg-black/60
    const dialog = screen.getByRole('dialog')
    const backdrop = dialog.querySelector('.bg-black\\/60') as HTMLElement
    fireEvent.click(backdrop)

    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('should use custom confirm and cancel labels', () => {
    render(
      <ConfirmModal
        {...defaultProps}
        confirmLabel="Yes, delete"
        cancelLabel="No, keep it"
      />
    )

    expect(screen.getByText('Yes, delete')).toBeInTheDocument()
    expect(screen.getByText('No, keep it')).toBeInTheDocument()
  })

  it('should show loading spinner and disable buttons when loading', () => {
    render(<ConfirmModal {...defaultProps} loading />)

    const confirmButton = screen.getByText('Confirm').closest('button')!
    const cancelButton = screen.getByText('Cancel').closest('button')!

    expect(confirmButton).toBeDisabled()
    expect(cancelButton).toBeDisabled()
  })

  it('should apply danger variant styles by default', () => {
    render(<ConfirmModal {...defaultProps} />)

    const confirmButton = screen.getByText('Confirm').closest('button')!
    expect(confirmButton.className).toContain('bg-red-600')
  })

  it('should apply warning variant styles', () => {
    render(<ConfirmModal {...defaultProps} variant="warning" />)

    const confirmButton = screen.getByText('Confirm').closest('button')!
    expect(confirmButton.className).toContain('bg-yellow-600')
  })
})
