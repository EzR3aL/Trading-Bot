interface EdgeBotsLogoProps {
  size?: number
  className?: string
}

export default function EdgeBotsLogo({ size = 32, className = '' }: EdgeBotsLogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      {/* Background rounded square */}
      <rect width="40" height="40" rx="10" fill="url(#bg-gradient)" />

      {/* Three ascending edge lines forming abstract "E" */}
      <path
        d="M10 28 L22 28"
        stroke="white"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M10 20 L26 20"
        stroke="white"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M10 12 L22 12"
        stroke="white"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      {/* Vertical bar of E */}
      <path
        d="M10 12 L10 28"
        stroke="white"
        strokeWidth="2.5"
        strokeLinecap="round"
      />

      {/* Upward arrow / chart line — the "edge" */}
      <path
        d="M24 26 L28 18 L32 14"
        stroke="#34d399"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Arrow head */}
      <path
        d="M29 14 L32 14 L32 17"
        stroke="#34d399"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      <defs>
        <linearGradient id="bg-gradient" x1="0" y1="0" x2="40" y2="40">
          <stop offset="0%" stopColor="#059669" />
          <stop offset="100%" stopColor="#047857" />
        </linearGradient>
      </defs>
    </svg>
  )
}
