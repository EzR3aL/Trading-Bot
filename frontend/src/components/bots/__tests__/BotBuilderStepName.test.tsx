import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BotBuilderStepName from '../BotBuilderStepName'

const defaultB: Record<string, string> = {
  name: 'Bot Name',
  namePlaceholder: 'Enter bot name',
  description: 'Description',
  descriptionPlaceholder: 'Enter description',
}

const defaultProps = {
  name: '',
  description: '',
  onNameChange: vi.fn(),
  onDescriptionChange: vi.fn(),
  b: defaultB,
}

describe('BotBuilderStepName', () => {
  it('renders name and description input fields', () => {
    render(<BotBuilderStepName {...defaultProps} />)

    expect(screen.getByLabelText('Bot Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Description')).toBeInTheDocument()
  })

  it('shows current bot name value', () => {
    render(<BotBuilderStepName {...defaultProps} name="My Trading Bot" />)

    expect(screen.getByDisplayValue('My Trading Bot')).toBeInTheDocument()
  })

  it('shows current description value', () => {
    render(<BotBuilderStepName {...defaultProps} description="A test bot" />)

    expect(screen.getByDisplayValue('A test bot')).toBeInTheDocument()
  })

  it('calls onNameChange when user types in name field', async () => {
    const onNameChange = vi.fn()
    const user = userEvent.setup()

    render(<BotBuilderStepName {...defaultProps} onNameChange={onNameChange} />)

    await user.type(screen.getByLabelText('Bot Name'), 'B')
    expect(onNameChange).toHaveBeenCalledWith('B')
  })

  it('calls onDescriptionChange when user types in description field', async () => {
    const onDescriptionChange = vi.fn()
    const user = userEvent.setup()

    render(<BotBuilderStepName {...defaultProps} onDescriptionChange={onDescriptionChange} />)

    await user.type(screen.getByLabelText('Description'), 'D')
    expect(onDescriptionChange).toHaveBeenCalledWith('D')
  })

  it('renders placeholders from translations', () => {
    render(<BotBuilderStepName {...defaultProps} />)

    expect(screen.getByPlaceholderText('Enter bot name')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Enter description')).toBeInTheDocument()
  })

  it('auto-focuses the name input', () => {
    render(<BotBuilderStepName {...defaultProps} />)

    // The name input has autoFocus attribute
    const nameInput = screen.getByLabelText('Bot Name')
    expect(nameInput).toHaveFocus()
  })
})
