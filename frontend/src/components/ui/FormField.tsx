import type { ReactNode } from 'react'

interface FormFieldProps {
  label: string
  error?: string | null
  required?: boolean
  children: ReactNode
  htmlFor?: string
  helpText?: string
}

/**
 * Reusable form field wrapper providing a label, optional help text,
 * and validation error message with proper aria attributes.
 */
export default function FormField({
  label,
  error,
  required,
  children,
  htmlFor,
  helpText,
}: FormFieldProps) {
  const describedByIds: string[] = []
  if (helpText && htmlFor) describedByIds.push(`${htmlFor}-help`)
  if (error && htmlFor) describedByIds.push(`${htmlFor}-error`)

  return (
    <div>
      <label
        htmlFor={htmlFor}
        className="block text-xs text-gray-400 mb-1.5 font-medium uppercase tracking-wider"
      >
        {label}
        {required && <span className="text-red-400 ml-0.5">*</span>}
      </label>

      {children}

      {helpText && (
        <p
          id={htmlFor ? `${htmlFor}-help` : undefined}
          className="text-xs text-slate-400 mt-1"
        >
          {helpText}
        </p>
      )}

      {error && (
        <p
          id={htmlFor ? `${htmlFor}-error` : undefined}
          className="text-xs text-red-400 mt-1"
          role="alert"
        >
          {error}
        </p>
      )}
    </div>
  )
}
