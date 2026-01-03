// Default catalog configurations
export const defaultCatalogs = [
    { id: 'watchly.rec', name: 'Top Picks for You', enabled: true, enabledMovie: true, enabledSeries: true, display_at_home: true, shuffle: false, description: 'Personalized recommendations based on your library' },
    { id: 'watchly.loved', name: 'More Like', enabled: true, enabledMovie: true, enabledSeries: true, display_at_home: true, shuffle: false, description: 'Recommendations similar to content you explicitly loved' },
    { id: 'watchly.watched', name: 'Because You Watched', enabled: true, enabledMovie: true, enabledSeries: true, display_at_home: true, shuffle: false, description: 'Recommendations based on your recent watch history' },
    { id: 'watchly.creators', name: 'From your favourite Creators', enabled: false, enabledMovie: true, enabledSeries: true, display_at_home: true, shuffle: false, description: 'Movies and series from your top 5 favorite directors and top 5 favorite actors' },
    { id: 'watchly.all.loved', name: 'Based on what you loved', enabled: false, enabledMovie: true, enabledSeries: true, display_at_home: true, shuffle: false, description: 'Recommendations based on all your loved items' },
    { id: 'watchly.liked.all', name: 'Based on what you liked', enabled: false, enabledMovie: true, enabledSeries: true, display_at_home: true, shuffle: false, description: 'Recommendations based on all your liked items' },
    { id: 'watchly.theme', name: 'Genre & Keyword Catalogs', enabled: true, enabledMovie: true, enabledSeries: true, display_at_home: true, shuffle: false, description: 'Dynamic catalogs based on your favorite genres, keyword, countries and many more. Just like netflix. Example: American Horror, Based on Novel or Book etc.' },
];

// Genre Constants
export const MOVIE_GENRES = [
    { id: '28', name: 'Action' }, { id: '12', name: 'Adventure' }, { id: '16', name: 'Animation' }, { id: '35', name: 'Comedy' }, { id: '80', name: 'Crime' }, { id: '99', name: 'Documentary' }, { id: '18', name: 'Drama' }, { id: '10751', name: 'Family' }, { id: '14', name: 'Fantasy' }, { id: '36', name: 'History' }, { id: '27', name: 'Horror' }, { id: '10402', name: 'Music' }, { id: '9648', name: 'Mystery' }, { id: '10749', name: 'Romance' }, { id: '878', name: 'Science Fiction' }, { id: '10770', name: 'TV Movie' }, { id: '53', name: 'Thriller' }, { id: '10752', name: 'War' }, { id: '37', name: 'Western' }
];

export const SERIES_GENRES = [
    { id: '10759', name: 'Action & Adventure' }, { id: '16', name: 'Animation' }, { id: '35', name: 'Comedy' }, { id: '80', name: 'Crime' }, { id: '99', name: 'Documentary' }, { id: '18', name: 'Drama' }, { id: '10751', name: 'Family' }, { id: '10762', name: 'Kids' }, { id: '9648', name: 'Mystery' }, { id: '10763', name: 'News' }, { id: '10764', name: 'Reality' }, { id: '10765', name: 'Sci-Fi & Fantasy' }, { id: '10766', name: 'Soap' }, { id: '10767', name: 'Talk' }, { id: '10768', name: 'War & Politics' }, { id: '37', name: 'Western' }
];
