// Small stroke icons (24px grid, drawn at 16-18px). Inline so the editor has no icon dependency.
const Svg = ({ size = 16, children, ...props }) => <svg
  width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
  strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}
>{children}</svg>

export const FlagIcon = (p) => <Svg {...p}><path d="M5 21V4" /><path d="M5 4h11l-2 4 2 4H5" /></Svg>
export const PhoneOffIcon = (p) => <Svg {...p}><path d="M10.7 13.3a13 13 0 0 1-2.4-3.4l1.5-1.5a1.5 1.5 0 0 0 .3-1.7L8.9 4.1A1.5 1.5 0 0 0 7.2 3.3L4.6 4a1.5 1.5 0 0 0-1.1 1.6 17 17 0 0 0 4.2 9.7" /><path d="M10.6 17.6a17 17 0 0 0 7.8 2.9 1.5 1.5 0 0 0 1.6-1.1l.7-2.6a1.5 1.5 0 0 0-.8-1.7l-2.6-1.2a1.5 1.5 0 0 0-1.7.3l-1.1 1.1" /><path d="M21 3 3 21" /></Svg>
export const NodeIcon = (p) => <Svg {...p}><circle cx="12" cy="12" r="9" /><circle cx="12" cy="10" r="3" /><path d="M6.6 18.4a6 6 0 0 1 10.8 0" /></Svg>
export const WrenchIcon = (p) => <Svg {...p}><path d="M14.7 6.3a4 4 0 0 0 5 5L21 13l-3 3-1.7-1.3a4 4 0 0 0-5-5L4 17v3h3l7.3-7.3" transform="translate(-1 -1)" /></Svg>
export const BranchIcon = (p) => <Svg {...p}><path d="M6 4v8a4 4 0 0 0 4 4h8" /><path d="m15 13 3 3-3 3" /></Svg>
export const PlusIcon = (p) => <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>
export const MinusIcon = (p) => <Svg {...p}><path d="M5 12h14" /></Svg>
export const FitIcon = (p) => <Svg {...p}><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></Svg>
export const TidyIcon = (p) => <Svg {...p}><rect x="9" y="3" width="6" height="5" rx="1" /><rect x="3" y="16" width="6" height="5" rx="1" /><rect x="15" y="16" width="6" height="5" rx="1" /><path d="M12 8v4M6 16v-2h12v2" /></Svg>
export const PhoneIcon = (p) => <Svg {...p}><path d="M5 4h3l2 5-2.5 1.5a11 11 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" /></Svg>
export const SettingsIcon = (p) => <Svg {...p}><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></Svg>
export const ArrowRightIcon = (p) => <Svg {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Svg>
export const TrashIcon = (p) => <Svg {...p}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></Svg>
export const CloseIcon = (p) => <Svg {...p}><path d="M6 6l12 12M18 6 6 18" /></Svg>
