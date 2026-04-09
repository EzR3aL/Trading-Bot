import {
  loginSchema,
  botNameSchema,
  exchangeCredentialsSchema,
  tradingParamsSchema,
  passwordChangeSchema,
  validateField,
} from '../validation'
import { z } from 'zod'

describe('loginSchema', () => {
  it('accepts valid username and password', () => {
    const result = loginSchema.safeParse({ username: 'admin', password: 'secret123' })
    expect(result.success).toBe(true)
  })

  it('rejects empty username', () => {
    const result = loginSchema.safeParse({ username: '', password: 'secret123' })
    expect(result.success).toBe(false)
  })

  it('rejects empty password', () => {
    const result = loginSchema.safeParse({ username: 'admin', password: '' })
    expect(result.success).toBe(false)
  })

  it('rejects username over 50 characters', () => {
    const result = loginSchema.safeParse({ username: 'a'.repeat(51), password: 'secret123' })
    expect(result.success).toBe(false)
  })
})

describe('botNameSchema', () => {
  it('accepts valid bot name', () => {
    const result = botNameSchema.safeParse({ name: 'BTC Edge Bot' })
    expect(result.success).toBe(true)
  })

  it('accepts name with umlauts', () => {
    const result = botNameSchema.safeParse({ name: 'Mein Bot ÄöÜ' })
    expect(result.success).toBe(true)
  })

  it('rejects empty name', () => {
    const result = botNameSchema.safeParse({ name: '' })
    expect(result.success).toBe(false)
  })

  it('rejects name over 100 characters', () => {
    const result = botNameSchema.safeParse({ name: 'a'.repeat(101) })
    expect(result.success).toBe(false)
  })

  it('rejects name with invalid characters', () => {
    const result = botNameSchema.safeParse({ name: 'Bot<script>' })
    expect(result.success).toBe(false)
  })
})

describe('exchangeCredentialsSchema', () => {
  it('accepts valid API credentials', () => {
    const result = exchangeCredentialsSchema.safeParse({
      apiKey: 'abcdefghij1234567890',
      apiSecret: 'secretkey1234567890',
    })
    expect(result.success).toBe(true)
  })

  it('accepts optional passphrase', () => {
    const result = exchangeCredentialsSchema.safeParse({
      apiKey: 'abcdefghij1234567890',
      apiSecret: 'secretkey1234567890',
      passphrase: 'myPassphrase',
    })
    expect(result.success).toBe(true)
  })

  it('rejects API key shorter than 10 characters', () => {
    const result = exchangeCredentialsSchema.safeParse({
      apiKey: 'short',
      apiSecret: 'secretkey1234567890',
    })
    expect(result.success).toBe(false)
  })

  it('rejects API secret shorter than 10 characters', () => {
    const result = exchangeCredentialsSchema.safeParse({
      apiKey: 'abcdefghij1234567890',
      apiSecret: 'short',
    })
    expect(result.success).toBe(false)
  })
})

describe('tradingParamsSchema', () => {
  it('accepts valid trading params', () => {
    const result = tradingParamsSchema.safeParse({
      leverage: 10,
      positionSize: 0.5,
    })
    expect(result.success).toBe(true)
  })

  it('accepts optional take profit and stop loss', () => {
    const result = tradingParamsSchema.safeParse({
      leverage: 5,
      positionSize: 1.0,
      takeProfitPercent: 2.5,
      stopLossPercent: 1.0,
    })
    expect(result.success).toBe(true)
  })

  it('rejects leverage below 1', () => {
    const result = tradingParamsSchema.safeParse({
      leverage: 0,
      positionSize: 0.5,
    })
    expect(result.success).toBe(false)
  })

  it('rejects leverage above 125', () => {
    const result = tradingParamsSchema.safeParse({
      leverage: 200,
      positionSize: 0.5,
    })
    expect(result.success).toBe(false)
  })

  it('rejects position size below 0.01', () => {
    const result = tradingParamsSchema.safeParse({
      leverage: 5,
      positionSize: 0.001,
    })
    expect(result.success).toBe(false)
  })
})

describe('passwordChangeSchema', () => {
  const validPassword = {
    currentPassword: 'OldPass123',
    newPassword: 'NewPass1!',
    confirmPassword: 'NewPass1!',
  }

  it('accepts valid password change', () => {
    const result = passwordChangeSchema.safeParse(validPassword)
    expect(result.success).toBe(true)
  })

  it('rejects empty current password', () => {
    const result = passwordChangeSchema.safeParse({
      ...validPassword,
      currentPassword: '',
    })
    expect(result.success).toBe(false)
  })

  it('rejects new password shorter than 8 characters', () => {
    const result = passwordChangeSchema.safeParse({
      ...validPassword,
      newPassword: 'Ab1!',
      confirmPassword: 'Ab1!',
    })
    expect(result.success).toBe(false)
  })

  it('rejects new password without uppercase letter', () => {
    const result = passwordChangeSchema.safeParse({
      ...validPassword,
      newPassword: 'newpass1!',
      confirmPassword: 'newpass1!',
    })
    expect(result.success).toBe(false)
  })

  it('rejects new password without lowercase letter', () => {
    const result = passwordChangeSchema.safeParse({
      ...validPassword,
      newPassword: 'NEWPASS1!',
      confirmPassword: 'NEWPASS1!',
    })
    expect(result.success).toBe(false)
  })

  it('rejects new password without digit', () => {
    const result = passwordChangeSchema.safeParse({
      ...validPassword,
      newPassword: 'NewPasss!',
      confirmPassword: 'NewPasss!',
    })
    expect(result.success).toBe(false)
  })

  it('rejects new password without special character', () => {
    const result = passwordChangeSchema.safeParse({
      ...validPassword,
      newPassword: 'NewPass12',
      confirmPassword: 'NewPass12',
    })
    expect(result.success).toBe(false)
  })

  it('rejects mismatched passwords', () => {
    const result = passwordChangeSchema.safeParse({
      ...validPassword,
      confirmPassword: 'DifferentPass1!',
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'))
      expect(paths).toContain('confirmPassword')
    }
  })
})

describe('validateField', () => {
  const nameSchema = z.string().min(1, 'Name is required')

  it('returns null for a valid value', () => {
    expect(validateField(nameSchema, 'hello')).toBeNull()
  })

  it('returns the error message for an invalid value', () => {
    expect(validateField(nameSchema, '')).toBe('Name is required')
  })

  it('works with complex schemas', () => {
    expect(validateField(loginSchema, { username: 'admin', password: 'pass' })).toBeNull()
  })

  it('returns first error for invalid complex schema', () => {
    const msg = validateField(loginSchema, { username: '', password: '' })
    expect(msg).toBeTruthy()
    expect(typeof msg).toBe('string')
  })
})
