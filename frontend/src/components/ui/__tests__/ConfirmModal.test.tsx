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

  it('should have aria-describedby pointing to the message body', () => {
    render(<ConfirmModal {...defaultProps} />)

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-describedby', 'confirm-desc')
    expect(screen.getByText('Are you sure you want to delete this bot?').id).toBe('confirm-desc')
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

  it('should NOT close on backdrop click by default', () => {
    const onCancel = vi.fn()
    render(<ConfirmModal {...defaultProps} onCancel={onCancel} />)

    const dialog = screen.getByRole('dialog')
    const backdrop = dialog.querySelector('.bg-black\\/60') as HTMLElement
    fireEvent.click(backdrop)

    expect(onCancel).not.toHaveBeenCalled()
  })

  it('should close on backdrop click when dismissOnBackdrop is true', () => {
    const onCancel = vi.fn()
    render(<ConfirmModal {...defaultProps} onCancel={onCancel} dismissOnBackdrop />)

    const dialog = screen.getByRole('dialog')
    const backdrop = dialog.querySelector('.bg-black\\/60') as HTMLElement
    fireEvent.click(backdrop)

    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('should ignore backdrop click while loading even with dismissOnBackdrop', () => {
    const onCancel = vi.fn()
    render(<ConfirmModal {...defaultProps} onCancel={onCancel} dismissOnBackdrop loading />)

    const dialog = screen.getByRole('dialog')
    const backdrop = dialog.querySelector('.bg-black\\/60') as HTMLElement
    fireEvent.click(backdrop)

    expect(onCancel).not.toHaveBeenCalled()
  })

  it('should close on Escape key', () => {
    const onCancel = vi.fn()
    render(<ConfirmModal {...defaultProps} onCancel={onCancel} />)

    fireEvent.keyDown(document, { key: 'Escape' })

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

  it('should focus the cancel button when opened', () => {
    render(<ConfirmModal {...defaultProps} />)
    const cancelButton = screen.getByText('Cancel').closest('button')!
    expect(document.activeElement).toBe(cancelButton)
  })

  it('should trap Tab navigation inside the dialog (wraps from last to first)', () => {
    render(<ConfirmModal {...defaultProps} />)
    const dialog = screen.getByRole('dialog')
    const confirmButton = screen.getByText('Confirm').closest('button')!
    const closeButton = screen.getByLabelText('Close')

    // Focus last focusable (Confirm) and press Tab -> should wrap to first (Close X)
    confirmButton.focus()
    expect(document.activeElement).toBe(confirmButton)
    fireEvent.keyDown(dialog, { key: 'Tab' })
    expect(document.activeElement).toBe(closeButton)
  })

  it('should trap Shift+Tab navigation inside the dialog (wraps from first to last)', () => {
    render(<ConfirmModal {...defaultProps} />)
    const dialog = screen.getByRole('dialog')
    const confirmButton = screen.getByText('Confirm').closest('button')!
    const closeButton = screen.getByLabelText('Close')

    // Focus first (Close X) and press Shift+Tab -> should wrap to last (Confirm)
    closeButton.focus()
    expect(document.activeElement).toBe(closeButton)
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(confirmButton)
  })

  it('should restore focus to previously focused element on close', () => {
    const triggerButton = document.createElement('button')
    triggerButton.textContent = 'Open'
    document.body.appendChild(triggerButton)
    triggerButton.focus()
    expect(document.activeElement).toBe(triggerButton)

    const { rerender } = render(<ConfirmModal {...defaultProps} />)
    // Modal mounted; focus should have moved to Cancel
    expect(document.activeElement).not.toBe(triggerButton)

    // Close modal
    rerender(<ConfirmModal {...defaultProps} open={false} />)
    expect(document.activeElement).toBe(triggerButton)

    document.body.removeChild(triggerButton)
  })
})
