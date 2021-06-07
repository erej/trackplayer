#!/usr/bin/env python
from mutagen.easyid3 import EasyID3
import json
import os
import time

json_data = []

def read_playlists(directory):
    playlists = os.scandir(directory)
    for playlist in playlists:
        songdir = os.path.join(directory, playlist.name)
        tracks = read_tracks(songdir)
        data = {
            'name': playlist.name,
            'tracks': tracks
        }
        json_data.append(data)

    write_json(json_data)
    playlistcount = len(json_data)
    print("Playlists found: %s" % playlistcount)
    for playlist in json_data:
        print(playlist.get('name'))
        print('tracks %d' % len(playlist.get('tracks', [])))

def read_tracks(directory):
    files = os.scandir(directory)
    tracks = []
    for song in files:
        if song.name.endswith('.mp3') and song.is_file:
            song_path = os.path.join(directory, song.name)
            song_number = song.name[0:3]
            id3_data = EasyID3(song_path)
            song_data = {
                'artist': id3_data.get('artist')[0],
                'title': id3_data.get('title')[0],
                'number': song_number,
                'file': song_path 
            }
            tracks.append(song_data)
    return tracks

def write_json(json_data):
    f = open('tracks.json', 'w')
    json.dump(json_data, f)
    f.close()
    print("JSON saved!")

playlist_dir = 'd:/music projects/backingtracks'
print("Generating JSON from "+playlist_dir)
start = time.time()
read_playlists(playlist_dir)
print("Playlist data generated is %s" % (time.time() - start))