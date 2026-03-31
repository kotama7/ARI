import React from 'react';

interface BadgeProps {
  variant?: 'green' | 'red' | 'yellow' | 'blue' | 'muted';
  children: React.ReactNode;
}

export function Badge({ variant = 'muted', children }: BadgeProps) {
  return <span className={`badge badge-${variant}`}>{children}</span>;
}
