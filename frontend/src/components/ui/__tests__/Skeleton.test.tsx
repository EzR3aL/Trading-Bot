import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import {
  SkeletonCard,
  SkeletonChart,
  SkeletonTable,
  SkeletonBotCard,
  DashboardSkeleton,
} from '../Skeleton'

describe('Skeleton Components', () => {
  describe('SkeletonCard', () => {
    it('should render without errors', () => {
      const { container } = render(<SkeletonCard />)
      expect(container.firstChild).toBeTruthy()
    })

    it('should contain skeleton pulse elements', () => {
      const { container } = render(<SkeletonCard />)
      const pulseElements = container.querySelectorAll('.skeleton-pulse')
      expect(pulseElements.length).toBe(3)
    })
  })

  describe('SkeletonChart', () => {
    it('should render with default height', () => {
      const { container } = render(<SkeletonChart />)
      const wrapper = container.firstChild as HTMLElement
      expect(wrapper.className).toContain('h-[250px]')
    })

    it('should render with custom height', () => {
      const { container } = render(<SkeletonChart height="h-[400px]" />)
      const wrapper = container.firstChild as HTMLElement
      expect(wrapper.className).toContain('h-[400px]')
    })

    it('should render 20 bar skeleton elements plus 1 label', () => {
      const { container } = render(<SkeletonChart />)
      // 20 bars + 1 label = 21 skeleton-pulse elements
      const pulseElements = container.querySelectorAll('.skeleton-pulse')
      expect(pulseElements.length).toBe(21)
    })
  })

  describe('SkeletonTable', () => {
    it('should render with default rows and cols', () => {
      const { container } = render(<SkeletonTable />)
      // Default: 5 rows + 1 header row = 6 flex rows. Each with 6 cols = 36 total skeleton elements
      const pulseElements = container.querySelectorAll('.skeleton-pulse')
      expect(pulseElements.length).toBe(36) // (5 + 1) * 6
    })

    it('should render with custom rows and cols', () => {
      const { container } = render(<SkeletonTable rows={3} cols={4} />)
      const pulseElements = container.querySelectorAll('.skeleton-pulse')
      expect(pulseElements.length).toBe(16) // (3 + 1) * 4
    })
  })

  describe('SkeletonBotCard', () => {
    it('should render without errors', () => {
      const { container } = render(<SkeletonBotCard />)
      expect(container.firstChild).toBeTruthy()
    })

    it('should contain multiple skeleton pulse elements', () => {
      const { container } = render(<SkeletonBotCard />)
      const pulseElements = container.querySelectorAll('.skeleton-pulse')
      expect(pulseElements.length).toBeGreaterThan(5)
    })
  })

  describe('DashboardSkeleton', () => {
    it('should render without errors', () => {
      const { container } = render(<DashboardSkeleton />)
      expect(container.firstChild).toBeTruthy()
    })

    it('should contain stat cards, charts, and table skeletons', () => {
      const { container } = render(<DashboardSkeleton />)
      // Should have many skeleton elements across cards, charts, and table
      const pulseElements = container.querySelectorAll('.skeleton-pulse')
      expect(pulseElements.length).toBeGreaterThan(20)
    })
  })
})
