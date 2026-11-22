import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Svg20({ size = 20, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

/* B2 Aturan merek: Logo/ikon-aplikasi (22/96 squircle tile, >= 21% clear space, vector tailed X) */
export function BrandAppTile({ size = 36 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 96 96"
      fill="none"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <rect width="96" height="96" rx="22" fill="var(--brand-tile)" />
      <path
        d="M27 26H38.5L48.5 41.8L58.5 26H70L54.2 49.4L72.5 76H60.8L48.2 57.2L37.5 74H26L42.8 49.2L27 26Z"
        fill="var(--brand-on-tile)"
      />
      <path
        d="M59.5 72.5C64.2 72.5 68.5 70.6 73.5 67.2"
        stroke="var(--brand-on-tile)"
        strokeWidth="6.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

/* B2 Aturan merek: Logo/wordmark ('tran' in Inter 700 -0.02em + original vector tailed X in Rokusho) */
export function BrandWordmark() {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '1px',
        fontFamily: 'var(--font-ui)',
        fontSize: '20px',
        lineHeight: '24px',
        fontWeight: 700,
        letterSpacing: '-0.02em',
        color: 'var(--text)',
        userSelect: 'none',
      }}
      aria-label="tranX"
    >
      <span>tran</span>
      <svg
        width="18"
        height="20"
        viewBox="0 0 36 40"
        fill="none"
        aria-hidden="true"
        style={{ display: 'block', marginTop: '1px' }}
      >
        <path
          d="M3 5H10.2L17.6 16.8L25 5H32.2L21.5 21.4L33.5 38H26.1L17.4 25.4L9.8 36.8H2.5L13.8 21.2L3 5Z"
          fill="var(--accent)"
        />
        <path
          d="M24.2 35.8C27.8 35.8 30.8 34.3 34.2 31.8"
          stroke="var(--accent)"
          strokeWidth="4.2"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}

export function IconMic(props: IconProps) {
  return (
    <Svg20 {...props}>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M8 21h8" />
      <path d="M12 18v3" />
    </Svg20>
  );
}

export function IconArrowUp(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M12 19V5" />
      <path d="M6 11l6-6 6 6" />
    </Svg20>
  );
}

export function IconStop(props: IconProps) {
  return (
    <Svg20 {...props}>
      <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
    </Svg20>
  );
}

export function IconPin(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M15 4.5l-4 4L7 10l-1.5 1.5 7 7L14 17l1.5-4 4-4" />
      <path d="M9 15l-4.5 4.5" />
      <path d="M14.5 4L20 9.5" />
    </Svg20>
  );
}

export function IconPinOff(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M3 3l18 18" />
      <path d="M15 4.5l-3.2 3.2M9.2 9.2L7 10l-1.5 1.5 7 7L14 17l.8-2.2M16.3 11.7l3.2-3.2" />
      <path d="M9 15l-4.5 4.5" />
      <path d="M14.5 4L20 9.5" />
    </Svg20>
  );
}

export function IconDots(props: IconProps) {
  return (
    <Svg20 {...props}>
      <circle cx="5" cy="12" r="1.25" fill="currentColor" />
      <circle cx="12" cy="12" r="1.25" fill="currentColor" />
      <circle cx="19" cy="12" r="1.25" fill="currentColor" />
    </Svg20>
  );
}

export function IconTrash(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M4 7h16" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12" />
      <path d="M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3" />
    </Svg20>
  );
}

export function IconEdit(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3z" />
      <path d="M13.5 6.5l3 3" />
    </Svg20>
  );
}

export function IconShare(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M8 9H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2h-2" />
      <path d="M12 14V4" />
      <path d="M9 7l3-3 3 3" />
    </Svg20>
  );
}

export function IconCopy(props: IconProps) {
  return (
    <Svg20 {...props}>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
    </Svg20>
  );
}

export function IconRefresh(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M20 11A8.1 8.1 0 0 0 4.5 9M4 5v4h4" />
      <path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4" />
    </Svg20>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M5 12l5 5L20 7" />
    </Svg20>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </Svg20>
  );
}

export function IconSearch(props: IconProps) {
  return (
    <Svg20 {...props}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M20 20l-4.5-4.5" />
    </Svg20>
  );
}

export function IconFolder(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M5 4h4l2 3h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
    </Svg20>
  );
}

export function IconBook(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M6 4h11a2 2 0 0 1 2 2v13H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
      <path d="M4 17a2 2 0 0 1 2-2h13" />
    </Svg20>
  );
}

export function IconKeyboard(props: IconProps) {
  return (
    <Svg20 {...props}>
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <path d="M7 10h.01M11 10h.01M15 10h.01M17 10h.01M7 14h10" />
    </Svg20>
  );
}

export function IconSettings(props: IconProps) {
  return (
    <Svg20 {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.08a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.08a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </Svg20>
  );
}

export function IconGlobe(props: IconProps) {
  return (
    <Svg20 {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3.6 9h16.8" />
      <path d="M3.6 15h16.8" />
      <path d="M11.5 3a17 17 0 0 0 0 18" />
      <path d="M12.5 3a17 17 0 0 1 0 18" />
    </Svg20>
  );
}

export function IconHelp(props: IconProps) {
  return (
    <Svg20 {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9a2.5 2.5 0 0 1 4.8 1c0 1.7-2.3 2.2-2.3 3.5" />
      <path d="M12 17h.01" />
    </Svg20>
  );
}

export function IconMail(props: IconProps) {
  return (
    <Svg20 {...props}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 7l9 6 9-6" />
    </Svg20>
  );
}

export function IconInfo(props: IconProps) {
  return (
    <Svg20 {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8h.01" />
      <path d="M11 12h1v4h1" />
    </Svg20>
  );
}

export function IconLogout(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M14 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-2" />
      <path d="M9 12h11" />
      <path d="M17 9l3 3-3 3" />
    </Svg20>
  );
}

export function IconMenu(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M4 7h16" />
      <path d="M4 12h16" />
      <path d="M4 17h16" />
    </Svg20>
  );
}

export function IconSidebarCollapse(props: IconProps) {
  return (
    <Svg20 {...props}>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M9 4v16" />
    </Svg20>
  );
}

export function IconChevronDown(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M6 9l6 6 6-6" />
    </Svg20>
  );
}

export function IconArrowsSwitch(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M7 10h13l-3.5-3.5" />
      <path d="M17 14H4l3.5 3.5" />
    </Svg20>
  );
}

export function IconText(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M4 6h16" />
      <path d="M10 6v12" />
      <path d="M15 11h5" />
      <path d="M17.5 11v7" />
    </Svg20>
  );
}

export function IconPhoto(props: IconProps) {
  return (
    <Svg20 {...props}>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <circle cx="9" cy="9" r="1.5" />
      <path d="M4 16l5-5 4 4 3-3 4 4" />
    </Svg20>
  );
}

export function IconFileText(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M14 3v4a1 1 0 0 0 1 1h4" />
      <path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z" />
      <path d="M9 9h2M9 13h6M9 17h6" />
    </Svg20>
  );
}

export function IconLink(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M10 14a3.5 3.5 0 0 0 5 0l4-4a3.5 3.5 0 0 0-5-5l-.5.5" />
      <path d="M14 10a3.5 3.5 0 0 0-5 0l-4 4a3.5 3.5 0 0 0 5 5l.5-.5" />
    </Svg20>
  );
}

export function IconCamera(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M5 7h2l2-2h6l2 2h2a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" />
      <circle cx="12" cy="13" r="3" />
    </Svg20>
  );
}

export function IconDownload(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
      <path d="M12 4v12" />
      <path d="M8 12l4 4 4-4" />
    </Svg20>
  );
}

export function IconColumns(props: IconProps) {
  return (
    <Svg20 {...props}>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M12 4v16" />
    </Svg20>
  );
}

export function IconX(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M18 6L6 18" />
      <path d="M6 6l12 12" />
    </Svg20>
  );
}

export function IconAlert(props: IconProps) {
  return (
    <Svg20 {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4" />
      <path d="M12 16h.01" />
    </Svg20>
  );
}

export function IconBookmark({ filled = false, ...props }: IconProps & { filled?: boolean }) {
  return (
    <Svg20 {...props}>
      <path
        d="M6 4h12a1 1 0 0 1 1 1v15l-7-4.5L5 20V5a1 1 0 0 1 1-1z"
        fill={filled ? 'currentColor' : 'none'}
      />
    </Svg20>
  );
}

export function IconHeadphones(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M4 13a8 8 0 0 1 16 0" />
      <rect x="4" y="13" width="3.5" height="6" rx="1.5" />
      <rect x="16.5" y="13" width="3.5" height="6" rx="1.5" />
    </Svg20>
  );
}

export function IconEye(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z" />
      <circle cx="12" cy="12" r="2.75" />
    </Svg20>
  );
}

export function IconBookOpen(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M2.5 6.5A2.5 2.5 0 0 1 5 4h5.5a2 2 0 0 1 1.5.7A2 2 0 0 1 13.5 4H19a2.5 2.5 0 0 1 2.5 2.5v12a.5.5 0 0 1-.5.5h-7a2 2 0 0 0-2 1.5A2 2 0 0 0 10 19H3a.5.5 0 0 1-.5-.5v-12z" />
      <path d="M12 5.2V19.5" />
    </Svg20>
  );
}

export function IconPlay(props: IconProps) {
  return (
    <Svg20 {...props}>
      <polygon points="7 5 19 12 7 19 7 5" fill="currentColor" stroke="currentColor" />
    </Svg20>
  );
}

export function IconPause(props: IconProps) {
  return (
    <Svg20 {...props}>
      <rect x="6.5" y="5" width="3.5" height="14" rx="1" fill="currentColor" stroke="none" />
      <rect x="14" y="5" width="3.5" height="14" rx="1" fill="currentColor" stroke="none" />
    </Svg20>
  );
}

export function IconSkipBack(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M6 6v12" />
      <polygon points="18 6 9.5 12 18 18 18 6" fill="currentColor" />
    </Svg20>
  );
}

export function IconSkipForward(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M18 6v12" />
      <polygon points="6 6 14.5 12 6 18 6 6" fill="currentColor" />
    </Svg20>
  );
}

export function IconAutoScroll(props: IconProps) {
  return (
    <Svg20 {...props}>
      <rect x="6" y="3.5" width="12" height="17" rx="6" />
      <path d="M12 7.5v4.5" />
      <path d="M9.5 10.5L12 13l2.5-2.5" />
    </Svg20>
  );
}

export function IconSliders(props: IconProps) {
  return (
    <Svg20 {...props}>
      <path d="M4 7h16" />
      <path d="M4 17h16" />
      <circle cx="9" cy="7" r="2" fill="var(--bg, #fff)" />
      <circle cx="15" cy="17" r="2" fill="var(--bg, #fff)" />
    </Svg20>
  );
}
