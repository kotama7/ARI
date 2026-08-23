import React from 'react';
import { Sidebar } from './Sidebar';

export function Layout({
  children,
  guiV2 = true,
}: {
  children: React.ReactNode;
  /** gui_v2 capability flag (gui_refresh Wave 2b) — forwarded to Sidebar. */
  guiV2?: boolean;
}) {
  return (
    <>
      <Sidebar guiV2={guiV2} />
      <main id="main">{children}</main>
    </>
  );
}
