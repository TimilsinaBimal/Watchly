movie_genres = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Science Fiction",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
}


series_genres = {
    10759: "Action & Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    10762: "Kids",
    9648: "Mystery",
    10763: "News",
    10764: "Reality",
    10765: "Sci-Fi & Fantasy",
    10766: "Soap",
    10767: "Talk",
    10768: "War & Politics",
    37: "Western",
}


MOVIE_GENRE_TO_ID_MAP = {genre: id for id, genre in movie_genres.items()}
SERIES_GENRE_TO_ID_MAP = {genre: id for id, genre in series_genres.items()}


# Adjectives to spice up titles based on genres
GENRE_ADJECTIVES = {
    # Movie Genres
    28: ["Adrenaline-Pumping", "Explosive", "Hard-Hitting"],  # Action
    12: ["Epic", "Globe-Trotting", "Daring"],  # Adventure
    16: ["Vibrant", "Imaginative", "Visually Stunning"],  # Animation
    35: ["Laugh-Out-Loud", "Witty", "Feel-Good"],  # Comedy
    80: ["Gritty", "Noir", "Underworld"],  # Crime
    99: ["Eye-Opening", "Compelling", "Real-Life"],  # Documentary
    18: ["Critically Acclaimed", "Powerful", "Emotional"],  # Drama
    10751: ["Wholesome", "Heartfelt", "Family-Favorite"],  # Family
    14: ["Magical", "Otherworldly", "Enchanting"],  # Fantasy
    36: ["Timeless", "Legendary", "Historic"],  # History
    27: ["Bone-Chilling", "Nightmarish", "Terrifying"],  # Horror
    10402: ["Melodic", "Rhythmic", "Musical"],  # Music
    9648: ["Mysterious", "Puzzle-Box", "Twisted"],  # Mystery
    10749: ["Heartwarming", "Passionate", "Bittersweet"],  # Romance
    878: ["Mind-Bending", "Futuristic", "Dystopian"],  # Science Fiction
    10770: ["Exclusive", "Feature-Length", "Made-for-TV"],  # TV Movie
    53: ["Edge-of-your-Seat", "Suspenseful", "Slow-Burn"],  # Thriller
    10752: ["Intense", "Heroic", "Battle-Hardened"],  # War
    37: ["Lawless", "Gunslinging", "Wild West"],  # Western
    # TV Specific Genres
    10759: ["Action-Packed", "High-Stakes", "Daring"],  # Action & Adventure
    10762: ["Fun-Filled", "Playful", "Educational"],  # Kids
    10763: ["In-Depth", "Current", "Breaking"],  # News
    10764: ["Unscripted", "Dramatic", "Binge-Worthy"],  # Reality
    10765: ["Fantastical", "Sci-Fi", "Supernatural"],  # Sci-Fi & Fantasy
    10766: ["Scandalous", "Dramatic", "Emotional"],  # Soap
    10767: ["Conversational", "Insightful", "Engaging"],  # Talk
    10768: ["Political", "Strategic", "Controversial"],  # War & Politics
}
