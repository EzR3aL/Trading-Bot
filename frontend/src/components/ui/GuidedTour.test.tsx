import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import GuidedTour, { TourHelpButton, type TourStep } from './GuidedTour'
import { useTourStore } from '../../stores/tourStore'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const map: Record<string, string> = {
        'tour.skip': 'Skip',
        'tour.next': 'Next',
        'tour.prev': 'Back',
        'tour.done': 'Done',
        'tour.helpButton': 'Help',
        'tour.testTitle': 'Test Title',
        'tour.testDesc': 'Test Description',
        'tour.testTitle2': 'Step 2 Title',
        'tour.testDesc2': 'Step 2 Description',
      }
      return map[key] || key
    },
  }),
}))

const testSteps: TourStep[] = [
  {
    target: "[data-tour=\"test-target\"]",
    titleKey: "tour.testTitle",
    descriptionKey: "tour.testDesc",
    position: "bottom",
  },
  {
    target: "[data-tour=\"test-target-2\"]",
    titleKey: "tour.testTitle2",
    descriptionKey: "tour.testDesc2",
    position: "bottom",
  },
]

function renderWithTarget(ui: React.ReactElement) {
  return render(
    <MemoryRouter>
      <div data-tour="test-target" style={{ width: 100, height: 50 }}>
        Target Element
      </div>
      <div data-tour="test-target-2" style={{ width: 100, height: 50 }}>
        Target Element 2
      </div>
      {ui}
    </MemoryRouter>,
  )
}

describe("GuidedTour", () => {
  beforeEach(() => {
    localStorage.clear()
    useTourStore.setState({
      completedTours: {},
      activeTour: null,
    })
  })

  describe("rendering", () => {
    it("does not render when inactive", () => {
      const { container } = renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} />,
      )
      expect(screen.queryByText("Test Title")).not.toBeInTheDocument()
      expect(container.querySelector("svg")).toBeNull()
    })

    it("renders when activated via store", () => {
      useTourStore.setState({ activeTour: "test-tour" })
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} />,
      )
      expect(screen.getByText("Test Title")).toBeInTheDocument()
      expect(screen.getByText("Test Description")).toBeInTheDocument()
    })

    it("does not render with empty steps", () => {
      useTourStore.setState({ activeTour: "test-tour" })
      const { container } = renderWithTarget(
        <GuidedTour tourId="test-tour" steps={[]} autoStart={false} />,
      )
      expect(container.querySelector("svg")).toBeNull()
    })

    it("shows step counter 1/2", () => {
      useTourStore.setState({ activeTour: "test-tour" })
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} />,
      )
      expect(screen.getByText("1/2")).toBeInTheDocument()
    })

    it("renders SVG overlay mask", () => {
      useTourStore.setState({ activeTour: "test-tour" })
      const { container } = renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} />,
      )
      const svg = container.querySelector("svg")
      expect(svg).toBeInTheDocument()
      const mask = container.querySelector("mask")
      expect(mask).toBeInTheDocument()
    })
  })

  describe("navigation", () => {
    it("advances to next step on Next click", () => {
      useTourStore.setState({ activeTour: "test-tour" })
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} />,
      )
      expect(screen.getByText("Test Title")).toBeInTheDocument()

      fireEvent.click(screen.getByText("Next"))

      expect(screen.getByText("Step 2 Title")).toBeInTheDocument()
      expect(screen.getByText("Step 2 Description")).toBeInTheDocument()
      expect(screen.getByText("2/2")).toBeInTheDocument()
    })

    it("shows Back button on step 2", () => {
      useTourStore.setState({ activeTour: "test-tour" })
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} />,
      )
      expect(screen.queryByText("Back")).not.toBeInTheDocument()

      fireEvent.click(screen.getByText("Next"))

      expect(screen.getByText("Back")).toBeInTheDocument()
    })

    it("goes back to previous step on Back click", () => {
      useTourStore.setState({ activeTour: "test-tour" })
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} />,
      )
      fireEvent.click(screen.getByText("Next"))
      expect(screen.getByText("Step 2 Title")).toBeInTheDocument()

      fireEvent.click(screen.getByText("Back"))

      expect(screen.getByText("Test Title")).toBeInTheDocument()
      expect(screen.getByText("1/2")).toBeInTheDocument()
    })

    it("shows Done button on last step", () => {
      useTourStore.setState({ activeTour: "test-tour" })
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} />,
      )
      expect(screen.getByText("Next")).toBeInTheDocument()
      expect(screen.queryByText("Done")).not.toBeInTheDocument()

      fireEvent.click(screen.getByText("Next"))

      expect(screen.getByText("Done")).toBeInTheDocument()
      expect(screen.queryByText("Next")).not.toBeInTheDocument()
    })
  })

  describe("completion", () => {
    it("marks tour complete on Done click", () => {
      useTourStore.setState({ activeTour: "test-tour" })
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} />,
      )
      fireEvent.click(screen.getByText("Next"))
      fireEvent.click(screen.getByText("Done"))

      const state = useTourStore.getState()
      expect(state.completedTours["test-tour"]).toBe(true)
      expect(state.activeTour).toBeNull()
    })

    it("marks tour complete on Skip click", () => {
      useTourStore.setState({ activeTour: "test-tour" })
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} />,
      )
      const skipButtons = screen.getAllByText("Skip")
      fireEvent.click(skipButtons[0])

      const state = useTourStore.getState()
      expect(state.completedTours["test-tour"]).toBe(true)
      expect(state.activeTour).toBeNull()
    })

    it("calls onComplete callback on finish", () => {
      const onComplete = vi.fn()
      useTourStore.setState({ activeTour: "test-tour" })
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} onComplete={onComplete} />,
      )
      fireEvent.click(screen.getByText("Next"))
      fireEvent.click(screen.getByText("Done"))

      expect(onComplete).toHaveBeenCalledTimes(1)
    })

    it("calls onComplete callback on skip", () => {
      const onComplete = vi.fn()
      useTourStore.setState({ activeTour: "test-tour" })
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={false} onComplete={onComplete} />,
      )
      const skipButtons = screen.getAllByText("Skip")
      fireEvent.click(skipButtons[0])

      expect(onComplete).toHaveBeenCalledTimes(1)
    })
  })

  describe("auto-start", () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it("auto-starts after 600ms delay for unseen tours", () => {
      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={true} />,
      )

      // Before timeout, tour should not be active
      expect(screen.queryByText("Test Title")).not.toBeInTheDocument()

      // Advance past the 600ms delay
      act(() => {
        vi.advanceTimersByTime(600)
      })

      expect(screen.getByText("Test Title")).toBeInTheDocument()
    })

    it("does not auto-start for completed tours", () => {
      useTourStore.setState({
        completedTours: { "test-tour": true },
        activeTour: null,
      })

      renderWithTarget(
        <GuidedTour tourId="test-tour" steps={testSteps} autoStart={true} />,
      )

      act(() => {
        vi.advanceTimersByTime(1000)
      })

      expect(screen.queryByText("Test Title")).not.toBeInTheDocument()
    })
  })
})

describe("TourHelpButton", () => {
  beforeEach(() => {
    localStorage.clear()
    useTourStore.setState({
      completedTours: {},
      activeTour: null,
    })
  })

  it("renders help text", () => {
    render(
      <MemoryRouter>
        <TourHelpButton tourId="test-tour" />
      </MemoryRouter>,
    )
    expect(screen.getByText("Help")).toBeInTheDocument()
  })

  it("activates tour on click", () => {
    render(
      <MemoryRouter>
        <TourHelpButton tourId="test-tour" />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByText("Help"))

    expect(useTourStore.getState().activeTour).toBe("test-tour")
  })

  it("has aria-label", () => {
    render(
      <MemoryRouter>
        <TourHelpButton tourId="test-tour" />
      </MemoryRouter>,
    )
    expect(screen.getByRole("button", { name: "Help" })).toBeInTheDocument()
  })
})

