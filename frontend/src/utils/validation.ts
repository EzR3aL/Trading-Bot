import { z } from 'zod'

export const loginSchema = z.object({
  username: z.string().min(1, 'Username is required').max(50),
  password: z.string().min(1, 'Password is required').max(128),
})

export const botNameSchema = z.object({
  name: z
    .string()
    .min(1, 'Bot name is required')
    .max(100, 'Bot name too long')
    .regex(/^[a-zA-Z0-9\s\-_äöüÄÖÜß]+$/, 'Invalid characters in bot name'),
})

export const exchangeCredentialsSchema = z.object({
  apiKey: z.string().min(10, 'API key too short'),
  apiSecret: z.string().min(10, 'API secret too short'),
  passphrase: z.string().optional(),
})

export const tradingParamsSchema = z.object({
  leverage: z.number().min(1).max(125),
  positionSize: z.number().min(0.01, 'Minimum position size is 0.01'),
  takeProfitPercent: z.number().min(0.1).max(1000).optional(),
  stopLossPercent: z.number().min(0.1).max(100).optional(),
})

export const passwordChangeSchema = z
  .object({
    currentPassword: z.string().min(1, 'Current password required'),
    newPassword: z
      .string()
      .min(8, 'Minimum 8 characters')
      .regex(/[A-Z]/, 'Must contain uppercase letter')
      .regex(/[a-z]/, 'Must contain lowercase letter')
      .regex(/[0-9]/, 'Must contain digit')
      .regex(/[^A-Za-z0-9]/, 'Must contain special character'),
    confirmPassword: z.string(),
  })
  .refine((d) => d.newPassword === d.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

/**
 * Validate a single value against a schema and return the first error message,
 * or null when the value is valid.
 */
export function validateField<T>(
  schema: z.ZodSchema<T>,
  value: unknown,
): string | null {
  const result = schema.safeParse(value)
  if (result.success) return null
  return result.error.issues[0]?.message ?? 'Invalid value'
}
