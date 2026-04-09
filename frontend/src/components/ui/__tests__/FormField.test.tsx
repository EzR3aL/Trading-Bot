import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import FormField from '../FormField'

describe('FormField', () => {
  it('should render label and children', () => {
    render(
      <FormField label="Username">
        <input type="text" data-testid="input" />
      </FormField>
    )

    expect(screen.getByText('Username')).toBeInTheDocument()
    expect(screen.getByTestId('input')).toBeInTheDocument()
  })

  it('should show required indicator when required', () => {
    render(
      <FormField label="Email" required>
        <input type="email" />
      </FormField>
    )

    expect(screen.getByText('*')).toBeInTheDocument()
  })

  it('should not show required indicator when not required', () => {
    render(
      <FormField label="Email">
        <input type="email" />
      </FormField>
    )

    expect(screen.queryByText('*')).not.toBeInTheDocument()
  })

  it('should show error message with role="alert"', () => {
    render(
      <FormField label="Email" error="Invalid email" htmlFor="email">
        <input id="email" type="email" />
      </FormField>
    )

    const error = screen.getByRole('alert')
    expect(error).toBeInTheDocument()
    expect(error).toHaveTextContent('Invalid email')
  })

  it('should set error element id based on htmlFor', () => {
    render(
      <FormField label="Email" error="Required" htmlFor="email">
        <input id="email" type="email" />
      </FormField>
    )

    const error = screen.getByRole('alert')
    expect(error.id).toBe('email-error')
  })

  it('should show help text', () => {
    render(
      <FormField label="Password" helpText="Must be at least 8 characters" htmlFor="password">
        <input id="password" type="password" />
      </FormField>
    )

    expect(screen.getByText('Must be at least 8 characters')).toBeInTheDocument()
  })

  it('should set help text id based on htmlFor', () => {
    render(
      <FormField label="Password" helpText="Use a strong password" htmlFor="password">
        <input id="password" type="password" />
      </FormField>
    )

    const helpText = screen.getByText('Use a strong password')
    expect(helpText.id).toBe('password-help')
  })

  it('should not render error when error is null', () => {
    render(
      <FormField label="Name" error={null}>
        <input type="text" />
      </FormField>
    )

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('should show both help text and error simultaneously', () => {
    render(
      <FormField label="Email" helpText="We won't share it" error="Invalid format" htmlFor="email">
        <input id="email" type="email" />
      </FormField>
    )

    expect(screen.getByText("We won't share it")).toBeInTheDocument()
    expect(screen.getByText('Invalid format')).toBeInTheDocument()
  })

  it('should link label to input via htmlFor', () => {
    render(
      <FormField label="Username" htmlFor="username">
        <input id="username" type="text" />
      </FormField>
    )

    const label = screen.getByText('Username')
    expect(label).toHaveAttribute('for', 'username')
  })
})
