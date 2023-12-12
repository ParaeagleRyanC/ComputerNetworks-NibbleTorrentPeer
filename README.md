# Simple BitTorrent Peer

BitTorrent is a communication protocol for peer-to-peer file sharing. A few important elements and principles allow the success of this protocol.
* Torrent File: A small file that tells your computer where to find pieces of the big file you want.
* Tracker: A helper that keeps track of who (peers on the network) has which pieces of the file.
* Peers: Other people sharing the file. You get pieces from them and share what you have.
* Downloading and Uploading: Getting pieces of the file from others while sharing what you have.
* Piece by Piece: The big file is split into smaller parts. You get them from different people at the same time.
* Completion: Once you have all the pieces, your computer puts them together to make the full file.

This **Simple BitTorrent Peer** program is the simplified version of the BitTorrent protocol as described above.
The principles are the same but is designed to run on local network with physically adjacent peers.

This program demonstrates the following knowledge and skills:
* Implementation of multi-threading programming. Tracker, downloading, and uploading run on their own threads.
* Ability to combine multiple network protocols into one single program. Including HTTP and TCP.
* Familiarity with peer-to-peer network.
