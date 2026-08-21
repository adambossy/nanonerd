import { describe, expect, test } from "vitest";
import { article, body, chunk, mark } from "./fixtures";
import { percentFor, readIdsFor } from "./reading";

describe("readIdsFor", () => {
  test("unions server read flags with local marks", () => {
    const input = body({
      chunks: [chunk({ id: 10, read: true }), chunk({ id: 11 }), chunk({ id: 12 })],
    });

    const output = [...readIdsFor(input, [mark({ chunk_id: 12 })])].sort();

    expect(output).toEqual([10, 12]);
  });

  test("ignores marks for chunks not in the body", () => {
    const output = [...readIdsFor(body(), [mark({ chunk_id: 999 })])];
    expect(output).toEqual([]);
  });

  test("returns only marks' ids when body is missing", () => {
    const output = [...readIdsFor(undefined, [mark({ chunk_id: 5 })])];
    expect(output).toEqual([5]);
  });
});

describe("percentFor", () => {
  const cases: Array<{
    name: string;
    body: ReturnType<typeof body> | undefined;
    marks: ReturnType<typeof mark>[];
    expected: number;
  }> = [
    { name: "no body → server percent", body: undefined, marks: [mark()], expected: 33.3 },
    {
      name: "server flags only",
      body: body({ chunks: [chunk({ id: 10, word_count: 25, read: true }), chunk({ id: 11, word_count: 75 })] }),
      marks: [],
      expected: 25,
    },
    {
      name: "local marks only",
      body: body({ chunks: [chunk({ id: 10, word_count: 25 }), chunk({ id: 11, word_count: 75 })] }),
      marks: [mark({ chunk_id: 11 })],
      expected: 75,
    },
    {
      name: "union, no double counting",
      body: body({ chunks: [chunk({ id: 10, word_count: 25, read: true }), chunk({ id: 11, word_count: 75 })] }),
      marks: [mark({ chunk_id: 10 }), mark({ chunk_id: 11 })],
      expected: 100,
    },
    {
      name: "zero total words → 0",
      body: body({ chunks: [chunk({ id: 10, word_count: 0 })] }),
      marks: [mark({ chunk_id: 10 })],
      expected: 0,
    },
    {
      name: "rounds to one decimal",
      body: body({ chunks: [chunk({ id: 10, word_count: 1, read: true }), chunk({ id: 11, word_count: 2 })] }),
      marks: [],
      expected: 33.3,
    },
  ];

  test.each(cases)("$name", ({ body: input, marks, expected }) => {
    const output = percentFor(article({ percent_read: 33.3 }), input, marks);
    expect(output).toBe(expected);
  });
});
