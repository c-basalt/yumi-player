import { describe, test, expect } from 'vitest'
import { cjkWidth, cjkTruncate } from '../cjkWidth'

describe('cjkWidth', () => {
    test('counts ASCII characters as width 1', () => {
        expect(cjkWidth('abc')).toBe(3)
        expect(cjkWidth('123')).toBe(3)
        expect(cjkWidth('!@#')).toBe(3)
    })

    test('counts CJK characters as width 2', () => {
        expect(cjkWidth('你好')).toBe(4)
        expect(cjkWidth('안녕')).toBe(4)
        expect(cjkWidth('こんにちは')).toBe(10)
    })

    test('counts full-width punctuation as width 2', () => {
        expect(cjkWidth('！')).toBe(2)    // FF01
        expect(cjkWidth('？')).toBe(2)    // FF1F
        expect(cjkWidth('：')).toBe(2)    // FF1A
        expect(cjkWidth('～')).toBe(2)    // FF5E
    })

    test('counts full-width space as width 2', () => {
        // eslint-disable-next-line no-irregular-whitespace
        expect(cjkWidth('　')).toBe(2)    // U+3000
        // eslint-disable-next-line no-irregular-whitespace
        expect(cjkWidth('a　b')).toBe(4)  // 1 + 2 + 1
        // eslint-disable-next-line no-irregular-whitespace
        expect(cjkWidth('你　好')).toBe(6) // 2 + 2 + 2
    })

    test('handles mixed ASCII and CJK characters', () => {
        expect(cjkWidth('Hello你好')).toBe(9)  // 5 (Hello) + 4 (你好)
        expect(cjkWidth('123あいう')).toBe(9)  // 3 (123) + 6 (あいう)
        expect(cjkWidth('Test測試')).toBe(8)   // 4 (Test) + 4 (測試)
    })

    test('handles mixed with full-width characters', () => {
        expect(cjkWidth('Hello！')).toBe(7)     // 5 (Hello) + 2 (！)
        expect(cjkWidth('你好！')).toBe(6)      // 4 (你好) + 2 (！)
        // eslint-disable-next-line no-irregular-whitespace
        expect(cjkWidth('Test　Test')).toBe(10) // 4 (Test) + 2 (　) + 4 (Test)
    })

    test('handles empty string', () => {
        expect(cjkWidth('')).toBe(0)
    })
})

describe('cjkTruncate', () => {
    test('does not truncate if total width is less than or equal to max', () => {
        expect(cjkTruncate('hello', 5)).toBe('hello')    // width 5 <= max 5
        expect(cjkTruncate('你好', 4)).toBe('你好')      // width 4 <= max 4
        expect(cjkTruncate('hi你好', 6)).toBe('hi你好')  // width 6 <= max 6
    })

    test('truncates when total width exceeds max', () => {
        expect(cjkTruncate('hello', 4)).toBe('he…')      // width 5 > max 4
        expect(cjkTruncate('你好', 4)).toBe('你好')      // width 4 <= max 4
        expect(cjkTruncate('hi你好', 5)).toBe('hi…')     // width 6 > max 5
    })

    test('truncates CJK strings with ellipsis', () => {
        expect(cjkTruncate('你好世界', 4)).toBe('你…')     // width 8 > max 4
        expect(cjkTruncate('こんにちは', 4)).toBe('こ…')   // width 10 > max 4
    })

    test('truncates strings with full-width characters', () => {
        expect(cjkTruncate('Hello！World', 6)).toBe('Hell…')  // width 11 > max 6
        expect(cjkTruncate('你好！世界', 4)).toBe('你…')      // width 8 > max 4
        // eslint-disable-next-line no-irregular-whitespace
        expect(cjkTruncate('Test　Test', 5)).toBe('Tes…')    // width 10 > max 5
    })

    test('truncates mixed ASCII and CJK strings', () => {
        expect(cjkTruncate('hello你好', 5)).toBe('hel…')     // width 9 > max 5
        expect(cjkTruncate('hi世界', 4)).toBe('hi…')         // width 6 > max 4
        expect(cjkTruncate('Test測試abc', 5)).toBe('Tes…')   // width 12 > max 5
    })

    test('handles empty string', () => {
        expect(cjkTruncate('', 5)).toBe('')
    })

    test('handles strings at or near max length', () => {
        // For ASCII strings
        expect(cjkTruncate('abc', 4)).toBe('abc')     // width 3 <= max 4
        expect(cjkTruncate('abcd', 4)).toBe('abcd')   // width 4 <= max 4

        // For CJK strings
        expect(cjkTruncate('你', 4)).toBe('你')       // width 2 <= max 4
        expect(cjkTruncate('你好', 4)).toBe('你好')   // width 4 <= max 4

        // For full-width punctuation
        expect(cjkTruncate('a！', 4)).toBe('a！')     // width 3 <= max 4
        expect(cjkTruncate('a！b', 4)).toBe('a！b')   // width 4 <= max 4
    })

    test('handles truncation at spaces', () => {
        expect(cjkTruncate('hello world', 5)).toBe('hel…')   // width 11 > max 5
        expect(cjkTruncate('abc def ghi', 4)).toBe('ab…')    // width 11 > max 4
        // eslint-disable-next-line no-irregular-whitespace
        expect(cjkTruncate('abc　def', 5)).toBe('abc…')      // width 7 > max 5
        expect(cjkTruncate('  a     ', 5)).toBe('  a…')        // width 7 > max 4
    })
})