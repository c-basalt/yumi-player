import { describe, test, expect } from 'vitest'
import { formatTime, formatLargeNumber } from '../utils'

describe('formatTime', () => {
    test('formats seconds only', () => {
        expect(formatTime(45)).toBe('0:45')
        expect(formatTime(5)).toBe('0:05')
        expect(formatTime(15)).toBe('0:15')
    })

    test('formats minutes and seconds', () => {
        expect(formatTime(65)).toBe('1:05')
        expect(formatTime(130)).toBe('2:10')
        expect(formatTime(905)).toBe('15:05')
        expect(formatTime(845)).toBe('14:05')
        expect(formatTime(615)).toBe('10:15')
    })

    test('formats hours, minutes and seconds', () => {
        expect(formatTime(3665)).toBe('1:01:05')
        expect(formatTime(7325)).toBe('2:02:05')
        expect(formatTime(36015)).toBe('10:00:15')
        expect(formatTime(37215)).toBe('10:20:15')
    })
})

describe('formatLargeNumber', () => {
    test('formats numbers under 1000', () => {
        expect(formatLargeNumber(123)).toBe('123')
        expect(formatLargeNumber(0)).toBe('0')
        expect(formatLargeNumber(999)).toBe('999')
    })

    test('formats numbers between 1000 and 9999', () => {
        expect(formatLargeNumber(1234)).toBe('1.2k')
        expect(formatLargeNumber(5678)).toBe('5.7k')
        expect(formatLargeNumber(9999)).toBe('10.0k')
    })

    test('formats numbers between 10000 and 99999', () => {
        expect(formatLargeNumber(12345)).toBe('1.2w')
        expect(formatLargeNumber(54321)).toBe('5.4w')
        expect(formatLargeNumber(99999)).toBe('10.0w')
    })

    test('formats numbers 100000 and above', () => {
        expect(formatLargeNumber(123456)).toBe('12w')
        expect(formatLargeNumber(987654)).toBe('99w')
        expect(formatLargeNumber(1234567)).toBe('123w')
    })
})