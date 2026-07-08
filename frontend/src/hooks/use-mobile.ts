import * as React from "react"

// 920 (not shadcn's default 768) to line up with the copilot @media (max-width:920px) breakpoint
// in copilot.css — below it the app switches to mobile page-scroll and the sidebar becomes a drawer.
const MOBILE_BREAKPOINT = 920

export function useIsMobile() {
  const [isMobile, setIsMobile] = React.useState<boolean | undefined>(undefined)

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    }
    mql.addEventListener("change", onChange)
    // Sync the initial value once on mount — matchMedia is an external store; this is the shadcn
    // use-mobile idiom (same intentional set-state-in-effect pattern suppressed elsewhere in the app).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return !!isMobile
}
