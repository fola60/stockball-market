import { IBM_Plex_Mono, Orbitron } from "next/font/google";

export const orbitron = Orbitron({
  variable: "--font-ui",
  subsets: ["latin"],
  weight: "variable",
  display: "swap",
});

export const plexMono = IBM_Plex_Mono({
  variable: "--font-data",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});
