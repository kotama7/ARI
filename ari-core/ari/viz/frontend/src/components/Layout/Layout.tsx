import React from 'react';
import { Sidebar } from './Sidebar';

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Sidebar />
      <div id="main">{children}</div>
    </>
  );
}
