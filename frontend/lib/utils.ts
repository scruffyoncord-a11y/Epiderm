import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Joins class names and resolves Tailwind conflicts (the helper shadcn/ui components expect at "@/lib/utils"). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
