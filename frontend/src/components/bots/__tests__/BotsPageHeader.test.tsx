import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import BotsPageHeader from '../BotsPageHeader'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('../../ui/GuidedTour', () => ({
  TourHelpButton: () => <button data-testid="tour-help">help</button>,
}))

describe('BotsPageHeader', () => {
  it('renders the page title', () => {
    render(<BotsPageHeader runningCount={0} onNewBot={() => {}} onStopAll={() => {}} />)
    expect(screen.getByText('bots.title')).toBeInTheDocument()
  })

  it('always renders the New Bot button', () => {
    render(<BotsPageHeader runningCount={0} onNewBot={() => {}} onStopAll={() => {}} />)
    expect(screen.getByLabelText('bots.newBot')).toBeInTheDocument()
  })

  it('hides Stop All when fewer than 2 bots are running', () => {
    render(<BotsPageHeader runningCount={1} onNewBot={() => {}} onStopAll={() => {}} />)
    expect(screen.queryByLabelText('bots.stopAll')).not.toBeInTheDocument()
  })

  it('shows Stop All when more than one bot is running', () => {
    render(<BotsPageHeader runningCount={3} onNewBot={() => {}} onStopAll={() => {}} />)
    const stopBtn = screen.getByLabelText('bots.stopAll')
    expect(stopBtn).toBeInTheDocument()
    expect(stopBtn.textContent).toContain('(3)')
  })

  it('calls onNewBot when New Bot clicked', () => {
    const onNewBot = vi.fn()
    render(<BotsPageHeader runningCount={0} onNewBot={onNewBot} onStopAll={() => {}} />)
    fireEvent.click(screen.getByLabelText('bots.newBot'))
    expect(onNewBot).toHaveBeenCalled()
  })

  it('calls onStopAll when Stop All clicked', () => {
    const onStopAll = vi.fn()
    render(<BotsPageHeader runningCount={2} onNewBot={() => {}} onStopAll={onStopAll} />)
    fireEvent.click(screen.getByLabelText('bots.stopAll'))
    expect(onStopAll).toHaveBeenCalled()
  })
})
