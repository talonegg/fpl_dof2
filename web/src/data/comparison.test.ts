import { describe, expect, it } from "vitest";
import { COMPARE_MAX, compareHref, isComparable, parseCompareIds } from "./comparison";

/**
 * The comparison seam is a URL two independently built routes agree on (DL-36), so the parsing is
 * the interesting half: it reads whatever a URL happens to contain, including one a reader typed.
 */
describe("comparison selection", () => {
  it("reads a list of ids out of the query string", () => {
    expect(parseCompareIds("?compare=3,1,2")).toEqual([3, 1, 2]);
  });

  it("preserves the order the players were chosen in", () => {
    expect(parseCompareIds("?compare=9,4")).toEqual([9, 4]);
  });

  it("returns nothing when the parameter is absent or empty", () => {
    expect(parseCompareIds("")).toEqual([]);
    expect(parseCompareIds("?other=1")).toEqual([]);
    expect(parseCompareIds("?compare=")).toEqual([]);
  });

  it("drops rubbish rather than throwing on it", () => {
    // An id in a URL is not a player; the caller still resolves these against the published data.
    expect(parseCompareIds("?compare=1,abc,-4,0,2.5,3")).toEqual([1, 3]);
  });

  it("drops duplicates", () => {
    expect(parseCompareIds("?compare=5,5,6")).toEqual([5, 6]);
  });

  it("caps the selection at the maximum the comparison view can render", () => {
    const ids = parseCompareIds("?compare=1,2,3,4,5,6");
    expect(ids.length).toBe(COMPARE_MAX);
    expect(ids).toEqual([1, 2, 3, 4]);
  });

  it("builds a link the comparison route can parse back", () => {
    const href = compareHref([7, 8]);
    expect(href).toBe("/compare?compare=7,8");
    expect(parseCompareIds(href.slice(href.indexOf("?")))).toEqual([7, 8]);
  });

  it("links to the bare route when nothing is selected", () => {
    expect(compareHref([])).toBe("/compare");
  });

  it("needs two players before there is anything to compare", () => {
    expect(isComparable([])).toBe(false);
    expect(isComparable([1])).toBe(false);
    expect(isComparable([1, 2])).toBe(true);
  });
});
