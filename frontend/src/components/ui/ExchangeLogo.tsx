interface ExchangeLogoProps {
  exchange: string
  size?: number
  className?: string
  showName?: boolean
}

/* Official Bitget icon mark — two interlocking arrows */
function BitgetLogo({ size = 18 }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="96 144 100 112" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M0 0c2.319 2.577 5.567 4.04 8.967 4.04h22.008c2.778 0 4.219-3.434 2.325-5.539l-43.524-48.364h24.052l24.456-26.952h-48.508l48.508-53.904h-29.317c-3.4 0-6.648 1.464-8.967 4.04l-49.204 54.677c-4.391 4.879-4.391 12.446 0 17.325z"
        transform="matrix(.530973 0 0 -.530051 127.8746508307 152.14125653)" fill="#1da2b4" fillRule="nonzero" />
      <path d="M0 0c-2.319-2.577-5.567-4.041-8.967-4.041h-22.008c-2.778 0-4.22 3.434-2.325 5.54l43.524 48.363h-24.052l-24.457 26.952h48.509l-48.509 53.904h29.318c3.4 0 6.648-1.463 8.967-4.04l49.204-54.677c4.391-4.879 4.391-12.446 0-17.325z"
        transform="matrix(.530973 0 0 -.530051 163.790248621 247.85786611)" fill="#1da2b4" fillRule="nonzero" />
    </svg>
  )
}

/* Official WEEX icon mark — geometric diamond/arrow shape, from weex.com */
function WeexLogo({ size = 18 }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 44 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path fillRule="evenodd" clipRule="evenodd"
        d="M24.1273 15.3082L30.3613 8.99947L21.6617 0L12.962 8.99947L19.196 15.2898L15.2972 19.2518L4.89248 8.99947L9.66157 4.14454H13.9173L17.1404 0.653227H8.11562L0 8.99947L15.2972 23.9816L21.6617 17.8003L28.0261 24L43.3233 8.99947L35.2077 0.671669H26.1829L29.406 4.16298H33.6617L38.4308 8.99947L28.0261 19.2703L24.1273 15.3082ZM21.6618 12.5566L18.0372 8.99823L21.6618 5.16772L25.2864 8.99823L21.6618 12.5566Z"
        fill="#D8AE15" />
    </svg>
  )
}

/* Official Hyperliquid / Hyper Foundation logo — wave mark */
function HyperliquidLogo({ size = 18 }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 150 150" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M146.26,76.01c.13,11.65-2.31,22.78-7.1,33.41-6.84,15.14-23.23,27.52-38.2,14.34-12.21-10.74-14.47-32.55-32.76-35.74-24.2-2.93-24.78,25.13-40.6,28.3-17.62,3.58-23.47-26.06-23.21-39.52,.26-13.46,3.84-32.38,19.15-32.38,17.62,0,18.81,26.68,41.18,25.24,22.15-1.51,22.54-29.27,37.01-41.16,12.49-10.27,27.18-2.74,34.53,9.62,6.82,11.43,9.81,24.85,9.97,37.88h.02Z"
        fill="#21F97E" />
    </svg>
  )
}

/* Bitunix icon mark — stylized "B" letterform, brand color green-yellow #B9F641 */
function BitunixLogo({ size = 18 }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M6 3h6c2.76 0 5 1.79 5 4 0 1.48-.87 2.77-2.15 3.45C16.68 11.13 18 12.64 18 14.5c0 2.49-2.24 4.5-5 4.5H6V3z
        M9 5.5v4h2.5c1.38 0 2.5-.9 2.5-2s-1.12-2-2.5-2H9z
        M9 12v4.5h3c1.38 0 2.5-.9 2.5-2.25S13.38 12 12 12H9z"
        fill="#B9F641" fillRule="evenodd" />
    </svg>
  )
}

/* BingX icon mark — abstract X/bowtie from four curved shapes, brand color blue #2954FE */
function BingXLogo({ size = 18 }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 12L3.5 4.5C3.5 4.5 5.5 2 8 4l4 4.5L16 4c2.5-2 4.5.5 4.5.5L12 12z" fill="#2954FE" />
      <path d="M12 12L3.5 19.5C3.5 19.5 5.5 22 8 20l4-4.5 4 4.5c2.5 2 4.5-.5 4.5-.5L12 12z" fill="#2954FE" />
    </svg>
  )
}

export function ExchangeIcon({ exchange, size = 18 }: { exchange: string; size?: number }) {
  const name = exchange.toLowerCase()
  const displayName = name === 'bitget' ? 'Bitget' : name === 'weex' ? 'Weex' : name === 'hyperliquid' ? 'Hyperliquid' : name === 'bitunix' ? 'Bitunix' : name === 'bingx' ? 'BingX' : exchange
  const icon = (() => {
    if (name === 'bitget') return <BitgetLogo size={size} />
    if (name === 'weex') return <WeexLogo size={size} />
    if (name === 'hyperliquid') return <HyperliquidLogo size={size} />
    if (name === 'bitunix') return <BitunixLogo size={size} />
    if (name === 'bingx') return <BingXLogo size={size} />
    return null
  })()
  if (!icon) return null
  return <span role="img" aria-label={displayName}>{icon}</span>
}

export default function ExchangeLogo({ exchange, size = 18, className = '', showName = true }: ExchangeLogoProps) {
  const name = exchange.toLowerCase()

  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <ExchangeIcon exchange={name} size={size} />
      {showName && (
        <span>{name === 'bitget' ? 'Bitget' : name === 'weex' ? 'Weex' : name === 'hyperliquid' ? 'Hyperliquid' : name === 'bitunix' ? 'Bitunix' : name === 'bingx' ? 'BingX' : exchange}</span>
      )}
    </span>
  )
}
