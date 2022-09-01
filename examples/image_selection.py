from backend.pipeline.iterable_dataset import IterablePipeline, InvalidDataException
from backend.data import BatchElement
from backend.client.gradio_client import GradioClient, GradioClientFront

from backend.api import CHEESE

from dataclasses import dataclass

from PIL import Image
from backend.utils.img_utils import url2img

import gradio as gr
import requests
import datasets
import time

# BatchElement should store everything you want to write to result dataset
# And everything you want to show the labeller
@dataclass
class ImageSelectionBatchElement(BatchElement):
    img1 : Image
    img2 : Image
    select : int = 0 # 0 None, -1 Left, 1, Right
    time : float = 0 # Time in seconds it took for user to select image

class ImageSelectionPipeline(IterablePipeline):
    def init_dataset(self):
        """
        This initializes the dataset we will be writing our results to.
        """
        return self.init_dataset_from_col_names(["img_1", "img_2", "selection", "time"])

    def preprocess(self, x):
        """
        Preprocess is called as soon as a new data element is drawn from iterator.
        It should handle invalid data by throwing the exception shown below.
        When an exception is thrown, the pipeline ignores the data and moves on to the next
        thing in the iterator.
        """
        try:
            img =  url2img(x["URL"], timeout = 1)
            img = img.resize((256, 256))
            return img
        except:
            raise InvalidDataException()
    
    def fetch(self) -> ImageSelectionBatchElement:
        """
        Fetch is meant to draw the next piece of data from the data source and construct a BatchElement
        out of it.
        """
        # IterablePipeline.fetch_next gets the next item from iterator and preprocesses it
        # It will return None if it could not get any new items
        data1 = self.fetch_next()
        data2 = self.fetch_next()
        
        return ImageSelectionBatchElement(data1, data2)
    
    def post(self, be : ImageSelectionBatchElement):
        """
        Post takes a finished (labelled) batch element and posts it to result dataset.
        """
        print("Post called")
        row = {"img_1" : be.img1, "img_2" : be.img2, "selection" : be.select, "time" : be.time}
        # IterablePipeline.post_row(...) takes a dict and adds it as a row to end of the result dataset
        # It also saves the result dataset and updates progress (in most cases it should always be called in post)
        self.post_row(row)

# IterablePipeline requires you to convert whatever dataset/data source you want to read from
# into an iterable
def make_iter():
    """
    Make iterator from LAION art dataset (laion/laion-art) parquet file
    """
    ds = datasets.load_dataset("laion/laion-art")
    ds = ds["train"].shuffle()

    return iter(ds)

# The Front object is what will be responsible for showing data to the labeller and collecting their responses
class ImageSelectionFront(GradioClientFront):
    def __init__(self):
        super().__init__()

        # All GradioClientFronts have three things you must use when constructing your own frontend for CHEESE
        # 1. self.demo, which is the demo that is run through gradio
        # 2. self.response, which is the method called to handle inputs/outputs going between Gradio and CHEESE
        # 3. self.data, which is the BatchElement your pipeline uses

        with gr.Blocks() as self.demo:
            with gr.Column():
                gr.Textbox("Of the two images below, select whichever one you prefer over the other.",
                    show_label = False, interactive = False
                )
                with gr.Row():
                    with gr.Column():
                        im_left = gr.Image(show_label = False)
                        btn_left = gr.Button("Select Left")
                        btn_left.style(full_width = True)
                    with gr.Column():
                        im_right = gr.Image(show_label = False)
                        btn_right = gr.Button("Select Right")
                        btn_right.style(full_width = True)

            # Note how both button clicks call response, but with different arguments
            # The arguments to response will later be passed to self.receive(...)
            # The result of response is whatever is outputted by self.send()
            def btn_left_click():
                return self.response(["Left"])
            def btn_right_click():
                return self.response(["Right"])

            btn_left.click(
                btn_left_click, inputs = [], outputs = [im_left, im_right]
            )

            btn_right.click(
                btn_right_click, inputs = [], outputs = [im_left, im_right]
            )

        self.response_timer = None

    # Response calls receive and passes along whatever input it got
    # We update self.data (an ImageSelectionBatchElement) appropriately
    def receive(self, *inp):
        res = inp[0]
        if res == "Left":
            self.data.select = -1
        elif res == "Right":
            self.data.select = 1
        
        # Log time it took them to make selection
        if self.response_timer is not None:
            self.data.time = time.time() - self.response_timer
            self.response_timer = None

    
    # This is what response eventually calls
    # We return the data from the BatchElement that we want to show the labeller
    def send(self):
        # Start timer whenever a new piece of data is shown
        self.response_timer = time.time()
        return self.data.img1, self.data.img2

# This class simply needs to be made to support connection between front end and the ClientManager in backend
class ImageSelectionClient(GradioClient):
    def init_front(self) -> str:
        return super().init_front(ImageSelectionFront)

if __name__ == "__main__":
    # The pipeline kwargs are inherited from IterablePipeline
    cheese = CHEESE(
        ImageSelectionPipeline, ImageSelectionClient,
        pipeline_kwargs = {
            "iter" : make_iter(), "write_path" : "./img_dataset_res", "force_new" : True, "max_length" : 5
        }
    )

    url1 = cheese.create_client(1)
    print(url1)

    while not cheese.finished:
        time.sleep(2)
    
    print("Done!")