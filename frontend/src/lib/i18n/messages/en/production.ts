import type { production } from '../ko/production.ts';

export const production_en: Record<keyof typeof production, string> = {
	'tpl.short-video.title': 'Short video',
	'tpl.short-video.desc': 'A short story that hooks in the first sentence',
	'tpl.short-video.use': 'Shorts · Reels',
	'tpl.short-video.text': 'Did you know that changing only the voice can change the mood of a video?\n\nRead a little slower and the same sentence becomes a warm story; read it faster and it turns into a lively introduction. Listen to a short take first, then find the pace that suits your content.',
	'tpl.course.title': 'Lesson · Tutorial',
	'tpl.course.desc': 'Clear narration that explains step by step',
	'tpl.course.use': 'Lessons · How-to',
	'tpl.course.text': 'In this lesson, we\'ll learn how to turn a script into speech.\n\nFirst, break what you want to say into short sentences. Next, choose a voice and a speed. Finally, use the preview to check the pronunciation and the flow between sentences.\n\nIf you\'re ready, let\'s build the first sentence together.',
	'tpl.product.title': 'Product · Service intro',
	'tpl.product.desc': 'From the moment of need to how to use it',
	'tpl.product.use': 'Service intro · Demo',
	'tpl.product.text': 'Want your own voice in a video but don\'t have time to record?\n\nWrite a script in Clone Voice and pick a registered voice. Save brand names you use often to the pronunciation dictionary and check them with a preview.\n\nDownload the finished audio and use it in your video edit.',
	'tpl.announcement.title': 'Announcement',
	'tpl.announcement.desc': 'A notice that makes the time and the action clear',
	'tpl.announcement.use': 'Events · Stores · Notices',
	'tpl.announcement.text': 'Attention, please. The event will begin shortly.\n\nPlease check your reservation at the entrance and take your assigned seat. If you need help, ask the nearest staff member.\n\nWe hope you enjoy your time with us. Thank you.',
	'prod.error.tooMany': 'You can register up to 100 pronunciations per script.',
	'prod.error.incomplete': 'Fill in both the word and how to read it, or remove the empty row.',
	'prod.error.length': 'Shorten the entry and remove tags or line breaks.',
	'prod.error.duplicate': 'Register the same word only once per language.'
};
