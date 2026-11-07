"use server";

import { revalidatePath } from "next/cache";
import { ApiError, apiRequest } from "@/lib/api";
import type { Guess } from "./types";

export type ActionState = { error?: string; guesses?: Guess[] };

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 401) return "Sign in again to continue.";
  if (error instanceof ApiError && typeof error.body === "object" && error.body !== null
      && "detail" in error.body && typeof error.body.detail === "string") {
    return error.body.detail;
  }
  return fallback;
}

export async function lockGuesses(day: string, _: ActionState, form: FormData): Promise<ActionState> {
  const guesses = [0, 1, 2].map((slot) => {
    const [direction, band] = String(form.get(`guess-${slot}`) ?? "").split(":");
    return { direction, band };
  });
  if (guesses.some((guess) => !guess.direction || !guess.band)) {
    return { error: "Choose a direction and size for all three players." };
  }
  try {
    return await apiRequest<{ guesses: Guess[] }>("/v1/blind-market/entries", {
      method: "POST", body: JSON.stringify({ day, guesses }),
    });
  } catch (error) {
    return { error: errorMessage(error, "Your guesses could not be saved. Try again.") };
  }
}

export async function claimReward(): Promise<ActionState> {
  try {
    await apiRequest("/v1/blind-market/claim", { method: "POST" });
    revalidatePath("/blind-market");
    return {};
  } catch (error) {
    return { error: errorMessage(error, "Your reward is saved. Try claiming it again shortly.") };
  }
}
