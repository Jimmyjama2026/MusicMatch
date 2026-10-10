import pandas as pd
# Import Path to help build file and folder locations.
from pathlib import Path
from difflib import get_close_matches
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics.pairwise import euclidean_distances



def load_songs():
    """Read the CSV and return a pandas DataFrame (a table of song rows)."""
    # Find the CSV in the same folder as this Python file.
    file_path = Path(__file__).parent / "dataset.csv"
    return pd.read_csv(file_path)


def find_matches(songs, song_search):
    """Return up to 10 song entries with titles spelled like the user's search."""
    # Skip missing titles, lowercase them, and keep each title once in a Python list.
    titles = songs["track_name"].dropna().str.lower().unique().tolist()

    #Find similar titles, get lower case, pull from titles list, 5 songs that match, and how strict to be(1 is most 0 is least)
    close_titles = get_close_matches(
        song_search.lower(), titles, n=5, cutoff=0.8
        )

    # isin checks which titles are in close_titles; songs[...] keeps those rows.
    matches = songs[songs["track_name"].str.lower().isin(close_titles)]
    # Compare title and artist together, so different artists can share a title.
    matches = matches.drop_duplicates(subset=["track_name", "artists"])
    # Keep 10 results and replace their old row labels with 0, 1, 2, ...
    matches = matches.head(10).reset_index(drop=True)
    return matches


def choose_song(matches):
    """Ask for a result number and return its song row, or None if no valid choice."""
    if matches.empty:
        print("No songs with that name found.")
        return None

    print(matches[["track_name", "artists"]].to_string())
    try:
        choice = int(input("Enter the number beside your song: "))
    except ValueError:
        print("Please enter a whole number.")
        return None

    if 0 <= choice < len(matches):
        # iloc selects a row by position; the returned row is a pandas Series.
        return matches.iloc[choice]

    print("That number isn't on the list.")
    return None

def get_features(song_table):
    """Return only the numerical comparison columns, keeping one row per song."""
    feature_names =["valence","tempo", "energy", "danceability"]
    
    return song_table[feature_names]

def get_closest_distances(all_scaled_features, liked_scaled_features):
    '''
    returns the euclidean_distances of each song compared with each favorite
    it takes the differene 

    Both inputs contain scaled features in the same column order.
    The returned array has one score per dataset song, in the original
    row order. Lower scores indicate closer matches to the favorites
    as a group. Favorites and duplicate tracks are not excluded here.
    '''
    distances = euclidean_distances(
        all_scaled_features, 
        liked_scaled_features
        )

    return distances.mean(axis=1)


def sort(candidate_song, average_distance, amount_of_songs_wanted ):
    #attach the average distance to the candidate songs to sort
    candidate_song["average_distances"] = average_distance
    ranked_songs = candidate_song.sort_values("average_distances")
    return ranked_songs.head(amount_of_songs_wanted)

def main():
    """Collect song choices until blank input, then display their table and features.

    Choices stay in memory for this run; they are not saved to a file yet.
    """
    
    songs = load_songs()
    songs = songs.drop_duplicates(subset=["track_name", "artists"])


    all_features = get_features(songs)
    scaler = MinMaxScaler()
    all_scaled_features = scaler.fit(all_features)
    # Create this once, before the loop, so earlier choices are kept.
    liked_songs = []
    while True:
        song_search = input("Enter a song title you enjoy (Enter to finish): ").strip()

        # Stop the loop if the input is blank or contains only spaces.
        if not song_search:
            break

        matches = find_matches(songs, song_search)
        selected_song = choose_song(matches)

        if selected_song is not None:
            # Save the whole song row, including its title, artist, and features.
            liked_songs.append(selected_song)
            print(f"You Chose: \033[1;3m{selected_song['track_name']}\033[0m by {selected_song['artists']}")
    if liked_songs:
        # Turn the list of song rows into a table after the user finishes.
        liked_table = pd.DataFrame(liked_songs)
        #Get the ID's of your favorite songs
        favorite_ids = liked_table["track_id"]

        #Check the dataset set songs and if they are a favorite
        isnt_favorite = ~songs["track_id"].isin(favorite_ids)
        candidate_songs = songs[isnt_favorite].copy()
        # Keep each track ID once if the user picked the same track again.
        liked_table=liked_table.drop_duplicates(subset=["track_id"])
        liked_song_features = get_features(liked_table)
        liked_scaled_features = scaler.transform(liked_song_features)

        #Remove duplicate candidate tracks
        candidate_songs =  candidate_songs.drop_duplicates(subset=["track_id"])

        #Scale the songs that arent favorite
        candidate_features = get_features(candidate_songs)
        candidate_scaled_features = scaler.transform(candidate_features)

        #compare candidates with your favorites
        average_distances = get_closest_distances(candidate_scaled_features,liked_scaled_features)

        #get the ___# lowest average songs
        closest_matches = sort(candidate_songs, average_distances, 5)
        print(f"\033[1:3mYour Closest Matches are\033[0m")
        print(f"_________________________")
        print(f"")
        for _, song in closest_matches.iterrows():
            print (f"\033[1:3m{song["track_name"]}\033[0m by {song["artists"]} with {float(song["average_distances"]):.3f} error")
    else:
        print("You didnt choose any songs")


# Start the program when this file is run directly.
if __name__ == "__main__":
    main()
