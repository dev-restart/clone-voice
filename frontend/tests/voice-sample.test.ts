import test from 'node:test';
import assert from 'node:assert/strict';
import { clampSampleRange, groupSampleTranscript, parseClockTime, sampleRangeKey, sampleTranscriptWindow, sampleTime } from '../src/lib/studio/voice-sample.ts';

test('short files and out-of-bounds edits never produce an invalid selection', () => {
	assert.deepEqual(clampSampleRange(0, 10, 1.25), { start: 0, end: 1.25 });
	assert.deepEqual(clampSampleRange(-10, 50, 12), { start: 0, end: 12 });
	assert.deepEqual(clampSampleRange(90, 2, 12), { start: 11.95, end: 12 });
	assert.equal(clampSampleRange(NaN, 5, 12), null);
	assert.equal(clampSampleRange(0, 5, 0), null);
});

test('nearby transcript windows stay bounded at either end of a long file', () => {
	assert.deepEqual(sampleTranscriptWindow(0, 10, 805), { start: 0, end: 30 });
	assert.deepEqual(sampleTranscriptWindow(20, 28, 90), { start: 9, end: 39 });
	assert.deepEqual(sampleTranscriptWindow(800, 805, 805), { start: 775, end: 805 });
	assert.deepEqual(sampleTranscriptWindow(0, 4.8, 4.8), { start: 0, end: 4.8 });
	assert.deepEqual(sampleTranscriptWindow(40, 100, 120), { start: 40, end: 70 });
});

test('word timings group into selectable phrases without applying a second offset', () => {
	const rows = groupSampleTranscript([
		{ start: 20.1, end: 20.8, text: '안녕하세요.' },
		{ start: 21, end: 22, text: ' 이 구간은 ' },
		{ start: 22.1, end: 24, text: '테스트입니다.' },
		{ start: 30, end: 31, text: '다음 문장입니다.' },
		{ start: NaN, end: 35, text: '잘못된 시간' },
		{ start: 36, end: 36, text: '빈 구간' }
	]);
	assert.deepEqual(rows, [
		{ start: 20.1, end: 20.8, text: '안녕하세요.' },
		{ start: 21, end: 24, text: '이 구간은 테스트입니다.' },
		{ start: 30, end: 31, text: '다음 문장입니다.' }
	]);
});

test('long word sequences do not form unbounded selection rows', () => {
	const rows = groupSampleTranscript(Array.from({ length: 24 }, (_, index) => ({
		start: 20 + index, end: 21 + index, text: 'word'
	})));
	assert.equal(rows.length, 3);
	assert.ok(rows.every((row) => row.end - row.start <= 10));
	assert.equal(rows[0].start, 20);
	assert.equal(rows.at(-1)?.end, 44);
});

test('source or millisecond-range changes invalidate a transcript binding', () => {
	assert.equal(sampleRangeKey(1, 20, 28), sampleRangeKey(1, 20.00001, 28));
	assert.notEqual(sampleRangeKey(1, 20, 28), sampleRangeKey(2, 20, 28));
	assert.notEqual(sampleRangeKey(1, 20, 28), sampleRangeKey(1, 20.1, 28));
	assert.equal(sampleTime(59.96), '1:00.0');
	assert.equal(sampleTime(805.3), '13:25.3');
});

test('clip times accept seconds and clock notation and reject everything else', () => {
	assert.equal(parseClockTime(''), null);
	assert.equal(parseClockTime('  '), null);
	assert.equal(parseClockTime('90'), 90);
	assert.equal(parseClockTime('1:30'), 90);
	assert.equal(parseClockTime('1:02:03'), 3723);
	assert.equal(parseClockTime('0:05.5'), 5.5);
	assert.ok(Number.isNaN(parseClockTime('abc')));
	assert.ok(Number.isNaN(parseClockTime('1:99:1:2')));
	assert.ok(Number.isNaN(parseClockTime('-5')));
});
