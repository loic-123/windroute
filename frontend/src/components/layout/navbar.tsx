"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Bike, Map, Route, Settings, Wind } from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: Wind },
  { href: "/workouts", label: "Seances", icon: Bike },
  { href: "/generate", label: "Generer", icon: Route },
  { href: "/routes", label: "Routes", icon: Map },
  { href: "/profile", label: "Profil", icon: Settings },
];

export function Navbar() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-gray-800 bg-gray-900/50 backdrop-blur">
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex items-center h-14 gap-8">
          <Link href="/" className="font-bold text-lg text-white tracking-tight">
            WindRoute
          </Link>

          <div className="flex gap-1">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors",
                  pathname === href
                    ? "bg-gray-800 text-white"
                    : "text-gray-400 hover:text-white hover:bg-gray-800/50"
                )}
              >
                <Icon size={16} />
                {label}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </nav>
  );
}
