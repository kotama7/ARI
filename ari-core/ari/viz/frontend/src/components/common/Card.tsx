import React from 'react';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  title?: string;
}

export function Card({ children, className, style, title }: CardProps) {
  return (
    <div className={`card${className ? ` ${className}` : ''}`} style={style}>
      {title && <div className="card-title">{title}</div>}
      {children}
    </div>
  );
}
