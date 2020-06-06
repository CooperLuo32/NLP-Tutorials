from tensorflow import keras
import tensorflow as tf
import utils
import time
import os
import numpy as np

UNITS = 128
EMB_DIM = 128
N_LAYERS = 2
BATCH_SIZE = 12
LEARNING_RATE = 1e-4


class ELMO(keras.Model):
    def __init__(self, v_dim, emb_dim, units, n_layers, lr):
        super().__init__()

        # encoder
        self.word_embed = keras.layers.Embedding(
            input_dim=v_dim, output_dim=emb_dim,  # [n_vocab, emb_dim]
            embeddings_initializer=keras.initializers.RandomNormal(0., 0.01),
            mask_zero=True,
        )
        f_rnn_cells = [tf.keras.layers.LSTMCell(units) for _ in range(n_layers)]
        self.f_stacked_lstm = tf.keras.layers.StackedRNNCells(f_rnn_cells)
        self.lstm_forward = tf.keras.layers.RNN(self.f_stacked_lstm, return_sequences=True)

        b_rnn_cells = [tf.keras.layers.LSTMCell(units) for _ in range(n_layers)]
        self.b_stacked_lstm = tf.keras.layers.StackedRNNCells(b_rnn_cells)
        self.lstm_backward = tf.keras.layers.RNN(self.b_stacked_lstm, return_sequences=True, go_backwards=True)
        self.word_pred = keras.layers.Dense(v_dim)

        self.cross_entropy = keras.losses.SparseCategoricalCrossentropy(from_logits=True)
        self.opt = keras.optimizers.Adam(lr, clipnorm=0.01)

    def __call__(self, seqs):
        embedded = self.word_embed(seqs)        # [n, step, dim]
        """
        0123    forward
         1234   backward
        1234    forward predict
         0123   backward predict
         123    overall prediction
        """
        mask = self.word_embed.compute_mask(seqs)
        f = self.lstm_forward(
            embedded[:, :-1],
            mask=mask[:, :-1],
            initial_state=self.f_stacked_lstm.get_initial_state(
                batch_size=embedded.shape[0], dtype=tf.float32))      # [n, step-1, dim]
        b = self.lstm_backward(
            embedded[:, 1:],
            mask=mask[:, 1:],
            initial_state=self.f_stacked_lstm.get_initial_state(
                batch_size=embedded.shape[0], dtype=tf.float32))      # [n, step-1, dim]
        b_reverse = tf.reverse(b, axis=[1])
        o = tf.concat((f[:, :-1], b_reverse[:, 1:]), axis=-1)       # [n, step-2, 2*dim]
        word_logits = self.word_pred(o)                     # [n, step-2, vocab]
        return word_logits

    def step(self, seqs):
        with tf.GradientTape() as tape:
            word_logits = self(seqs)
            loss = self.cross_entropy(seqs[:, 1:-1], word_logits)
        grads = tape.gradient(loss, self.trainable_variables)
        self.opt.apply_gradients(zip(grads, self.trainable_variables))
        return loss, word_logits

    def inference(self, x):
        s = self.encode(x)
        done, i, s = self.decoder_eval.initialize(
            self.dec_embeddings.variables[0],
            start_tokens=tf.fill([x.shape[0], ], self.start_token),
            end_token=self.end_token,
            initial_state=s,
        )
        pred_id = np.zeros((x.shape[0], self.max_pred_len), dtype=np.int32)
        for l in range(self.max_pred_len):
            o, s, i, done = self.decoder_eval.step(
                time=l, inputs=i, state=s, training=False)
            pred_id[:, l] = o.sample_id
        return pred_id


def main():
    data = utils.MRPCSingle("./MRPC", rows=1000)
    print("num word: ", data.num_word)
    model = ELMO(data.num_word, emb_dim=EMB_DIM,
                 units=UNITS, n_layers=N_LAYERS, lr=LEARNING_RATE)
    t0 = time.time()
    for t in range(2500):
        seqs = data.sample(BATCH_SIZE)
        loss, pred = model.step(seqs)
        if t % 50 == 0:
            pred = pred[0].numpy().argmax(axis=1)
            t1 = time.time()
            print(
                "\n\nstep: ", t,
                "| time: %.2f" % (t1 - t0),
                "| loss: %.3f" % loss.numpy(),
                "\n| tgt: ", " ".join([data.i2v[i] for i in seqs[0, 1:]]),
                "\n| prd: ", " ".join([data.i2v[i] for i in pred]),
                )
            t0 = t1
    os.makedirs("./visual_helper/elmo", exist_ok=True)
    model.save_weights("./visual_helper/elmo/model.ckpt")


if __name__ == "__main__":
    main()