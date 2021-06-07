#!/usr/bin/env python
import alsaaudio
import gpiozero
import json
import vlc
import queue
import re
import time
from threading import Timer
from pathlib import Path
import lcddriver


class RepeatedTimer(object):
    def __init__(self, interval, function, *args, **kwargs):
        self._timer     = None
        self.interval   = interval
        self.function   = function
        self.args       = args
        self.kwargs     = kwargs
        self.is_running = False
        self.start()

    def _run(self):
        self.is_running = False
        self.start()
        self.function(*self.args, **self.kwargs)

    def start(self):
        if not self.is_running:
            self._timer = Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        self._timer.cancel()
        self.is_running = False

class CustomIcons:
    def getNoteIcon(self):
        customChar = (0B00000,0B01111,0B01001,0B01001,0B11011,0B11011,0B00000,0B00000)
        return customChar
    
class TrackPlayer:
    def __init__(self):
        self.initialize()

    def init_lcd(self):
        self.lcd = None
        self.lcd = lcddriver.lcd()
        self.lcd.lcd_clear()

    def initialize(self):
        # Inputs
        self.footswitch_next = gpiozero.Button(16)
        self.footswitch_prev = gpiozero.Button(12)
        self.footswitch_play = gpiozero.Button(26)
        self.rotary_button = gpiozero.Button(22)
        self.rotary_clk = gpiozero.Button(17)
        self.rotary_dt = gpiozero.Button(27)
        self.rotary_dt_value = 0
        self.rotary_clk_value = 0
        
        #LCD
        self.init_lcd()
        self.lcd.lcd_display_string("Ahnuld 1.0", 1)
        self.lcd.lcd_display_string("Initializing", 2)
        
        # Mediaplayer
        self.instance = vlc.Instance("--aout=alsa")
        self.media = None
        self.mediaplayer = self.instance.media_player_new()
        self.alsa = alsaaudio.Mixer(alsaaudio.mixers()[0])


        # Button and rotary switch queues
        self.command_queue = queue.Queue()

        self.timer = None
        
        # Variables
        self.playing = False # Don't play automatically
        self.track_number = 0
        self.track_count = 0 # songs in the selected playlist
        self.playlist_number = 0
        self.playlist_count = 0 # playlists
        self.tracks = {} # json tiedosto, jossa kaikki tiedot
        self.track = None
        self.track_length = 0
        self.track_playtime = 0
        self.last_track = 0
        self.current_track = 0
        
        # default volume
        self.volume_right = 1
        self.volume_left = 1
        # if both of these states are 1, go to settings
        self.footswitch_next_state = False
        self.footswitch_prev_state = False

        # settings etc.
        self.mode_play = 'play'
        self.mode_idle = 'idle'
        self.mode_settings = 'settings'
        self.mode_playlist = 'playlist'
        self.mode = self.mode_idle
        self.run_program = True
        self.settings = {}
        self.lcd.lcd_clear()
        self.lcd.lcd_display_string('Reading settings...', 1)
        self.read_settings()
        self.lcd.lcd_display_string('Reading tracks...', 2)
        self.read_tracks()
        self.lcd_show_track_information()
        self.init_buttons_and_rotary() # initialize the rotary things
        self.play_thread = None

    # Rotary pins can be monitored as buttons, when dt is turned, clk side is actived and therefore "pressed"
    def queue_rotary_dt_button(self):
        if not self.playing and self.rotary_clk.is_pressed:
            self.command_queue.put('rotary_next')

    def queue_rotary_clk_button(self):
        if not self.playing and self.rotary_dt.is_pressed:
            self.command_queue.put('rotary_prev')

    def queue_footswitch_prev(self):
        if self.footswitch_prev.is_pressed:
            self.footswitch_prev_state = True
            self.command_queue.put('footswitch_prev')

    def queue_footswitch_prev_held(self):
        if self.footswitch_prev.is_pressed and self.footswitch_prev_state:
            self.command_queue.put('footswitch_prev')

    def queue_footswitch_next(self):
        if self.footswitch_next.is_pressed:
            self.footswitch_next_state = True
            self.command_queue.put('footswitch_next')

    def queue_footswitch_next_held(self):
        if self.footswitch_next.is_pressed and self.footswitch_next_state:
            self.command_queue.put('footswitch_next')

    def queue_footswitch_play(self):
        if self.footswitch_play.is_pressed:
            if self.playing:
                self.command_queue.put('footswitch_stop')
            else:
                self.command_queue.put('footswitch_play')

    def footswitch_next_reset_state(self):
        print('reset next')
        self.footswitch_next_state = False

    def footswitch_prev_reset_state(self):
        print('reset prev')
        self.footswitch_prev_state = False
    
    def queue_rotary_button(self):
        if self.rotary_button.is_pressed:
            self.command_queue.put('footswitch_rotary')
            
    def init_buttons_and_rotary(self):
        self.command_queue.put(self.mode_idle)
        self.rotary_clk.when_pressed = self.queue_rotary_clk_button
        self.rotary_dt.when_pressed = self.queue_rotary_dt_button
        self.rotary_button.when_pressed = self.queue_rotary_button
        self.footswitch_play.when_pressed = self.queue_footswitch_play
        self.footswitch_next.when_pressed = self.queue_footswitch_next
        self.footswitch_prev.when_pressed = self.queue_footswitch_prev

    def lcd_display_error(self, line1 = '', line2 = '', line3 = '', line4 = ''):
        self.lcd.lcd_clear()
        self.lcd_update_display(line1, line2, line3, line4)

    def read_tracks(self):
        try:
            f = open('tracks.json')
            self.tracks = json.load(f)
            f.close()
        except IOError as e:
            self.lcd_display_error('tracks JSON file loading failed', e)
        self.playlist_count = len(self.tracks)
        self.track_count = len(self.tracks[self.playlist_number].get('tracks', []))
        self.last_track = self.track_count - 1

    def read_settings(self):
        try:
            f = open('settings.json')
            self.settings = json.load(f)
            f.close()
        except IOError as e:
            self.lcd_display_error('settings JSON file loading failed')
        self.playlist_number = self.settings.get('playlist_number', 0)
        self.track_number = self.settings.get('track_number', 0)
        self.volume_left = self.settings.get('volume_left', 0.8)
        self.volume_right = self.settings.get('volume_right', 0.8)

    def sort_tracks(self, track):
        return track.get('number', 1)

    def lcd_show_track_information(self):
        tracks = self.tracks[self.playlist_number].get('tracks', [])
        tracks.sort(key=self.sort_tracks)
        self.track = tracks[self.track_number] 
        number = self.track.get('number', '000')
        artist = self.track.get('artist', 'No artist')
        title = self.track.get('title', 'No title')
        self.track_length = self.track.get('length', 0)
        title = re.sub(r'\s\([\W\w\d\s]*\)\Z', '', title)
        artist = re.sub(r'\s\([\W\w\d\s]*\)\Z', '', artist)
        line1_max = 16
        line2_max = 20
        if len(artist) > line1_max:
            artist_line1 = artist[:line1_max]
            artist_line2 = artist[line1_max:]
        else:
            artist_line1 = artist
            artist_line2 = ''
        if len(title) > line2_max:
            title_line3 = title[:line2_max]
            title_line4 = title[line2_max:]
        else:
            title_line3 = title
            title_line4 = ''

        line1 = "%s - %s" % (number, artist_line1)
        line2 = artist_line2 if len(artist_line2) > 0 else title_line3
        line3 = title_line3 if len(artist_line2) > 0 else title_line4
        line4 = title_line4 if len(artist) > line2_max and len(title) > line2_max else ''
        self.lcd_update_display(line1, line2, line3, line4)
        pass

    def lcd_show_playlist_information(self):
        playlist = self.tracks[self.playlist_number]
        playlist_name = "Name: %s" % playlist.get('name', 'No name')
        playlist_track_count = "Tracks: %s" % len(playlist.get('tracks', []))
        self.lcd_update_display(playlist_name, playlist_track_count)

    def lcd_clear_line(self, line_number = 1):
        clearLine = " " * 20
        self.lcd.lcd_display_string(clearLine, line_number)

    def lcd_update_display(self, line1='', line2='', line3='', line4=''):
        self.lcd.lcd_clear()
        self.lcd.lcd_display_string(line1, 1)
        self.lcd.lcd_display_string(line2, 2)
        self.lcd.lcd_display_string(line3, 3)
        self.lcd.lcd_display_string(line4, 4)

    def lcd_write_line(self, string, line_number=1, clear_line=True):
        if clear_line:
            self.lcd_clear_line(line_number)
        self.lcd.lcd_display_string(string, line_number)

    def lcd_update_track_time(self):
        self.track_playtime = self.mediaplayer.get_time()
        playhead_milliseconds = int(self.track_playtime)
        playhead_seconds=(playhead_milliseconds/1000)%60
        playhead_seconds = int(playhead_seconds)
        playhead_minutes = (playhead_milliseconds/(1000*60))%60
        playhead_minutes = int(playhead_minutes)
        track_minutes, track_seconds = divmod(self.track_length, 60) 
        play_information = '{:02d}:{:02d} / {:02d}:{:02d}'.format(playhead_minutes, playhead_seconds, int(track_minutes), int(track_seconds))
        if self.lcd:
            self.lcd_write_line(play_information, 4, True)            

    def load_track(self, filename):
        self.lcd_write_line('Loading the MP3...', 4, True)    
        self.media = self.instance.media_new(filename)
        self.mediaplayer.set_media(self.media)

    def play_track(self):
        self.init_lcd()
        self.lcd_show_track_information()
        filename = None
        try:
            self.timer = RepeatedTimer(1, self.lcd_update_track_time)
            if self.current_track != self.track:
                filename = self.track.get('file')
                self.load_track(filename)
                self.current_track = self.track
                self.lcd_clear_line(4)
            if self.media:
                self.mediaplayer.audio_set_volume(100)
                self.mediaplayer.play()
        except Exception as e:
            self.lcd_display_error('', '', 'Error in playing', self.track.get('number', ''))
            print(e)

    def stop_track(self):
        self.init_lcd()
        self.lcd_show_track_information()
        self.playing = False
        self.mediaplayer.stop()
        self.timer.stop()
        self.timer = None

    def select_track(self, direction='next'):
        increment = 1 if direction == 'next' else -1
        self.track_number += increment
        if self.track_number < 0:
            self.track_number = self.last_track
        elif self.track_number > self.last_track:
            self.track_number = 0
        self.lcd_show_track_information()

    def select_playlist(self, direction='next'):
        increment = 1 if direction == 'next' else -1
        self.playlist_number += increment
        self.track_number = 0 # set track number to 0
        if self.playlist_number < 0:
            self.playlist_number = self.playlist_count - 1 #switch to last one
        elif self.playlist_number > self.playlist_count - 1:
            self.playlist_number = 0 # switch to first one
        self.track_count = len(self.tracks[self.playlist_number].get('tracks', []))
        self.last_track = self.track_count - 1
        self.lcd_show_playlist_information()

    def main(self):
        while self.run_program:
            if self.mode == self.mode_settings:
                self.lcd_update_display('settings')
            command_value = self.command_queue.get()
            print(command_value)
            if not self.playing:
                # Rotary: turn
                if command_value == 'rotary_next' or command_value == 'rotary_prev':
                    if self.mode == self.mode_idle:
                        direction = 'next' if command_value == 'rotary_next' else 'prev'
                        self.select_track(direction)
                    elif self.mode == self.mode_playlist:
                        direction = 'next' if command_value == 'rotary_next' else 'prev'
                        self.select_playlist(direction)
                # Rotary: push
                elif command_value == 'footswitch_rotary':
                    if self.mode == self.mode_playlist:
                        self.mode = self.mode_idle
                        self.lcd_show_track_information()
                    elif self.mode == self.mode_idle:
                        self.mode = self.mode_playlist
                        self.lcd_show_playlist_information()
                # Footswitch: prev
                elif command_value == 'footswitch_prev':
                    if self.mode == self.mode_idle:
                        self.select_track('prev')
                    if self.mode == self.mode_playlist:
                        self.select_playlist('prev')
                # Footswitch: next
                elif command_value == 'footswitch_next':
                    if self.mode == self.mode_idle:
                        self.select_track('next')
                    if self.mode == self.mode_playlist: 
                        self.select_playlist('next')
                # Footswitch: play
                elif command_value == 'footswitch_play':
                    self.track_playtime = 0
                    self.mode = self.mode_play
                    self.playing = True
                    self.play_track()
            if self.playing:                    
                # Footswitch: stop
                if command_value == 'footswitch_stop':
                    self.playing = False
                    self.mode = self.mode_idle
                    self.stop_track()
                



tp = TrackPlayer()
tp.main()
