"use server";

import { revalidatePath } from "next/cache";
import { ApiError, apiRequest, getInstruments } from "@/lib/api";
import type { Called, Guess, Media } from "./types";

export type CallState = { error?: string; called?: Called; media?: Media | null };
export type ClaimState = { error?: string; claimed?: boolean };

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 401) return "Sign in again to continue.";
  if (error instanceof ApiError && typeof error.body === "object" && error.body !== null
      && "detail" in error.body && typeof error.body.detail === "string") {
    return error.body.detail;
  }
  return fallback;
}

/** Locks one player's call and returns that player, revealed. */
export async function callPlayer(day: string, slot: number, guess: Guess): Promise<CallState> {
  let called: Called;
  try {
    called = await apiRequest<Called>("/v1/blind-market/entries", {
      method: "POST", body: JSON.stringify({ day, slot, guess }),
    });
  } catch (error) {
    return { error: errorMessage(error, "Your call could not be saved. Try again.") };
  }
  // The portrait is a nice-to-have: the reveal still works without it.
  const instrument = await getInstruments()
    .then((instruments) => instruments.find((item) => item.id === called.result.instrument_id))
    .catch(() => undefined);
  revalidatePath("/daily-games");
  return {
    called,
    media: instrument ? { player_image_version: instrument.player_image_version, club_badge_version: instrument.club_badge_version } : null,
  };
}

export async function claimReward(): Promise<ClaimState> {
  try {
    await apiRequest("/v1/blind-market/claim", { method: "POST" });
    revalidatePath("/daily-games");
    return { claimed: true };
  } catch (error) {
    return { error: errorMessage(error, "Your reward is saved. Try claiming it again shortly.") };
  }
}
