import datetime
import io
import json
import os
import queue

import requests
import tweepy
from google.cloud import vision
from google.cloud.vision import types

# Load config file
with open('config.json', 'r') as f:
    config = json.load(f)

# Authenticate to Google Vision API
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = config['google']['application-credentials-file']

# Authenticate to Twitter
auth = tweepy.OAuthHandler(config['twitter']['apiKey'], config['twitter']['apiSecret'])
auth.set_access_token(config['twitter']['accessToken'], config['twitter']['accessSecret'])

api = tweepy.API(auth, wait_on_rate_limit=True, wait_on_rate_limit_notify=True)

bannedKeywords = ['image', 'gif', 'giphy', 'tumblr', 'imgur', 'we heart it', '8tracks.com', 'gfycat', '/m/02j71',
                  'wallpaper', 'imgur', 'flickr', 'blog', '8tracks.com', 'clutch.ua', 'jpeg', 'pinterest',
                  'portable network graphics', '/m/083vt', 'Automanas.lt', 'Kwejk.pl', 'Demotywatory.pl']

head = {'Authorization': 'Bearer ' + config['contextMonster']['apiKey']}


class ResponseTweet:

    def __init__(self, text, in_response):
        self.text = text
        self.in_response = in_response


class TweetStreamListener(tweepy.StreamListener):

    def on_status(self, status):
        if (status.user.id == int(config['twitter']['userId'])
                and 'media' in status.entities and not hasattr(status, 'retweeted_status')):
            image = status.entities['media'][0]['media_url']
            report(annotate(image), image, status.id)


def annotate(path):
    client = vision.ImageAnnotatorClient()

    if path.startswith('http') or path.startswith('gs:'):
        image = types.Image()
        image.source.image_uri = path

    else:
        with io.open(path, 'rb') as image_file:
            content = image_file.read()

        image = types.Image(content=content)

    web_detection = client.web_detection(image=image).web_detection

    return web_detection


def report(annotations, image_url, tweet_id):
    global counter, id_length, publish
    if counter % 2 == 0:
        pages = []
        matches = []
        partial_matches = []
        ratings = []
        include_url = False
        if annotations.pages_with_matching_images:
            for page in annotations.pages_with_matching_images:
                pages.append(page.url)

        if annotations.full_matching_images:
            for image in annotations.full_matching_images:
                matches.append(image.url)

        if annotations.partial_matching_images:
            for image in annotations.partial_matching_images:
                partial_matches.append(image.url)

        if annotations.web_entities:
            max_score = annotations.web_entities[0].score
            for entity in annotations.web_entities:
                if len(entity.description) > 0 and entity.description.lower() not in bannedKeywords:
                    ratings.append(
                        {
                            'keyword_text': entity.description,
                            'rate': entity.score
                        }
                    )
            limit = 230 if include_url else 265 - id_length
            tweet = '. @archillect Related keywords: "'
            for entity in annotations.web_entities:
                keyword = entity.description
                if len(tweet) + len(keyword) <= limit:
                    if len(keyword) > 0 and keyword.lower() not in bannedKeywords:
                        tweet += keyword + ', '
                else:
                    break
            if max_score > 0.35:
                data = {
                    'image': image_url,
                    'archillect_tweet': int(tweet_id),
                    'pages': pages,
                    'matches': matches,
                    'partial_matches': partial_matches,
                    'ratings': ratings
                }
                r = requests.post(url=config['contextMonster']['apiUrl'], json=data, headers=head)
                if r.status_code == requests.codes.created:
                    tweet = tweet[:-2]
                    monster_id = json.loads(r.text)['id']
                    if include_url:
                        tweet += '" Full report: ' + config['contextMonster']['reportUrl'] + str(monster_id)
                    else:
                        tweet += '" Ref: ' + str(monster_id)

                    if q.qsize() == 3:
                        while not q.empty():
                            enqueued = q.get()
                            api.update_status(enqueued.text, in_reply_to_status_id=enqueued.in_response)
                            print(datetime.datetime.now().strftime('%H:%M:%S') + ' Published: ' + enqueued.text)
                    q.put(ResponseTweet(tweet, tweet_id))
                    print(datetime.datetime.now().strftime('%H:%M:%S')
                          + ' Added to queue (' + str(q.qsize()) + '): ' + tweet)
                    id_length = len(str(monster_id + 1))

                    if counter % 24 == 0:
                        if publish != '':
                            api.update_status(publish)
                            print(datetime.datetime.now().strftime('%H:%M:%S') + ' Published')
                        publish = ratings[0]["keyword_text"] + ' https://context.monster/' + str(monster_id) \
                                  + ' https://twitter.com/archillect/status/' + str(tweet_id)
                        print(datetime.datetime.now().strftime('%H:%M:%S') + ' Saved: ' + publish)

    counter += 1


counter = 0
id_length = 4
q = queue.Queue()
publish = ''
tweetStreamListener = TweetStreamListener()
myStream = tweepy.Stream(auth=api.auth, listener=tweetStreamListener)
myStream.filter(follow=[config['twitter']['userId']])
