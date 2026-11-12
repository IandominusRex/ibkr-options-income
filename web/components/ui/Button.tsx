import clsx from "clsx";
import { forwardRef, type ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "quiet";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  block?: boolean;
};

const VARIANT: Record<ButtonVariant, string> = {
  // Lime means act: only the primary variant may carry it.
  primary: "bg-primary text-on-primary enabled:hover:bg-primary-deep disabled:bg-sunk",
  secondary: "bg-sunk text-content enabled:hover:bg-sunk-deep disabled:bg-sunk",
  // A quiet button that cannot be pressed stays transparent and only dims, so the one you cannot
  // press never looks fuller than the one you can (DESIGN.md Open Decisions, resolved 2026-11-07).
  quiet: "bg-transparent text-content enabled:hover:bg-sunk",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", block = false, className, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      data-variant={variant}
      className={clsx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-[18px]",
        // DESIGN.md title type (17px, 700); the 0.98 press is motion, so reduced motion drops it.
        "text-[1.0625rem] font-bold transition-transform duration-[90ms] motion-safe:enabled:active:scale-[0.98]",
        "disabled:cursor-default disabled:text-muted",
        VARIANT[variant],
        block && "w-full",
        className,
      )}
      {...rest}
    />
  );
});
