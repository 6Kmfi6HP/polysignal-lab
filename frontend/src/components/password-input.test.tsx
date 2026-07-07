/**
 * Input: { describe, expect, it } from 'vitest', { render } from '@testing-library/react', userEvent from '@testing-library/user-event', { PasswordInput } from './password-input', vitest, @testing-library/react, @testing-library/user-event, ./password-input
 * Output: None
 * Pos: UI Layer - UI components
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PasswordInput } from './password-input'

describe('PasswordInput', () => {
  it('renders the password input correctly', async () => {
    const { getByPlaceholderText, getByRole } = await render(
      <PasswordInput placeholder='password' />
    )

    const passwordInput = getByPlaceholderText('password')
    const showPasswordButton = getByRole('button', { name: /show password/i })

    expect(passwordInput).toBeInTheDocument()
    expect(passwordInput).toHaveAttribute('type', 'password')
    expect(showPasswordButton).toBeVisible()
  })

  it('toggles the password visibility when the show password button is clicked', async () => {
    const { getByPlaceholderText, getByRole } = await render(
      <PasswordInput placeholder='password' />
    )

    const passwordInput = getByPlaceholderText('password')
    const showPasswordButton = getByRole('button', { name: /show password/i })

    expect(passwordInput).toHaveAttribute('type', 'password')
    expect(showPasswordButton).toBeInTheDocument()

    await userEvent.click(showPasswordButton)

    expect(passwordInput).toHaveAttribute('type', 'text')
    const hidePasswordButton = getByRole('button', { name: /hide password/i })
    expect(hidePasswordButton).toBeInTheDocument()

    await userEvent.click(hidePasswordButton)

    expect(passwordInput).toHaveAttribute('type', 'password')
    expect(getByRole('button', { name: /show password/i }))
      .toBeInTheDocument()
  })

  it('disables the show password button when the password input is disabled', async () => {
    const { getByPlaceholderText, getByRole } = await render(
      <PasswordInput placeholder='password' disabled />
    )

    const passwordInput = getByPlaceholderText('password')
    const showPasswordButton = getByRole('button', { name: /show password/i })
    expect(showPasswordButton).toBeDisabled()
    expect(passwordInput).toBeDisabled()
  })

})
