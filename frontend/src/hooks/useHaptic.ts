/**
 * Haptic feedback hook using the Web Vibration API.
 * Gracefully degrades on unsupported devices (iOS Safari).
 */
export default function useHaptic() {
  const canVibrate = typeof navigator !== 'undefined' && 'vibrate' in navigator

  const light = () => { if (canVibrate) navigator.vibrate(15) }
  const medium = () => { if (canVibrate) navigator.vibrate(40) }
  const heavy = () => { if (canVibrate) navigator.vibrate([40, 30, 40]) }
  const success = () => { if (canVibrate) navigator.vibrate([15, 50, 15]) }
  const error = () => { if (canVibrate) navigator.vibrate([80, 30, 80]) }

  return { light, medium, heavy, success, error, canVibrate }
}
