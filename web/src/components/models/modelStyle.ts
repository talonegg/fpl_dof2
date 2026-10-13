import type { ModelChoice } from "../../data/model";

/** Line colour and dash pattern per model, so charts read without colour too. */
export const COLOURS: Record<ModelChoice, string> = {
  champion: "#2f6fed",
  challenger: "#d9822b",
  engine: "#6b7280",
  a: "#16a34a",
  a_odds: "#a21caf",
};
export const DASHES: Record<ModelChoice, string> = {
  champion: "",
  challenger: "6 3",
  engine: "2 3",
  a: "8 3 2 3",
  a_odds: "1 2",
};
